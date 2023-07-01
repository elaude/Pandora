from __future__ import annotations  # allows type hint PCA inside PCA class

import math

import numpy as np
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.model_selection import GridSearchCV

from pandora.custom_types import *
from pandora.custom_errors import *


class PCA:
    """Class structure encapsulating PCA results.

    This class provides a wrapper for PCA results.

    Attributes:
        pca_data (pd.DataFrame): Pandas dataframe with shape (n_samples, n_pcs + 2) that contains the PCA results.
            The dataframe contains one row per sample and has the following columns:
                - sample_id (str): ID of the respective sample.
                - population (str): Name of the respective population.
                - PC{i} for i in range(n_pcs) (float): data for the i-th PC for each sample,
                  0-indexed, so the first PC corresponds to column PC0
        explained_variances (npt.NDArray[float]): Numpy ndarray containing the explained variances for each PC (shape=(n_pcs,))
        n_pcs (int): number of principal components
        pc_vectors: Numpy ndarray of shape (n_samples, n_pcs) containing the PCA result matrix.
    """

    def __init__(
        self,
        pca_data: pd.DataFrame,
        explained_variances: npt.NDArray[float],
        n_pcs: int,
    ):
        """
        Initializes a new PCA object.

        Args:
            pca_data (pd.DataFrame): Pandas dataframe containing the sample ID, population and PC-Vector of all samples.
                The dataframe should contain one row per sample.
                Pandora expects the following columns:
                    - sample_id (str): ID of the respective sample.
                    - population (str): Name of the respective population.
                    - PC{i} for i in range(n_pcs) (float): data for the i-th PC for each sample,
                      0-indexed, so the first PC corresponds to column PC0
            explained_variances (npt.NDArray[float]): Numpy ndarray containing the explained variances for each PC (shape=(n_pcs,))
            n_pcs (int): number of principal components

        Raises:
            PandoraException:
                - explained_variances is not a 1D numpy array or contains more/fewer values than n_pcs
                - pca_data does not contain a "sample_id" column
                - pca_data does not contain a "population" column
                - pca_data does not contain (the correct amount of) PC{i} columns
        """
        if explained_variances.ndim != 1:
            raise PandoraException(
                f"Explained variance should be a 1D numpy array. "
                f"Instead got {explained_variances.ndim} dimensions."
            )
        if explained_variances.shape[0] != n_pcs:
            raise PandoraException(
                f"Explained variance required for each PC. Got {n_pcs} but {len(explained_variances)} variances."
            )

        if "sample_id" not in pca_data.columns:
            raise PandoraException("Column `sample_id` required.")

        if "population" not in pca_data.columns:
            raise PandoraException("Column `population` required.")

        if pca_data.shape[1] != n_pcs + 2:
            # two extra columns (sample_id, population)
            raise PandoraException(
                f"One data column required for each PC. Got {n_pcs} but {pca_data.shape[1] - 2} PC columns."
            )

        pc_columns = [f"PC{i}" for i in range(n_pcs)]
        if not all(c in pca_data.columns for c in pc_columns):
            raise PandoraException(
                f"Expected all of the following columns to be present in pca_data: {pc_columns}."
                f"Instead got {[c for c in pca_data.columns if c not in ['sample_id', 'population']]}"
            )

        self.n_pcs = n_pcs
        self.explained_variances = explained_variances
        self.pca_data = pca_data.sort_values(by="sample_id").reset_index(drop=True)
        self.pc_vectors: npt.NDArray[float] = self._get_pca_data_numpy()

    def _get_pca_data_numpy(self) -> np.ndarray:
        """
        Converts the PCA data to a numpy array.

        Returns:
             np.ndarray: Array of shape (n_samples, self.n_pcs).
                 Does not contain the sample IDs or populations.
        """
        return self.pca_data[[f"PC{i}" for i in range(self.n_pcs)]].to_numpy()

    def get_optimal_kmeans_k(self, k_boundaries: Tuple[int, int] = None) -> int:
        """
        Determines the optimal number of clusters k for K-Means clustering according to the Bayesian Information Criterion (BIC).

        Args:
            k_boundaries (Tuple[int, int]): Minimum and maximum number of clusters. If None is given,
                determine the boundaries automatically.
                If self.pca_data.populations is not identical for all samples, use the number of distinct populations,
                otherwise use the square root of the number of samples as maximum max_k.
                The minimum min_k is min(max_k, 3).

        Returns:
            int: the optimal number of clusters between min_n and max_n
        """
        if k_boundaries is None:
            # check whether there are distinct populations given
            n_populations = self.pca_data.population.unique().shape[0]
            if n_populations > 1:
                max_k = n_populations
            else:
                # if only one population: use the square root of the number of samples
                max_k = int(math.sqrt(self.pca_data.shape[0]))
            min_k = min(3, max_k)
        else:
            min_k, max_k = k_boundaries

        grid_search = GridSearchCV(
            estimator=GaussianMixture(),
            param_grid={"n_components": range(min_k, max_k)},
            scoring=lambda estimator, X: -estimator.bic(X),
        )

        grid_search.fit(self.pc_vectors)
        return grid_search.best_params_["n_components"]

    def cluster(self, kmeans_k: int = None) -> KMeans:
        """
        Fits a K-Means cluster to the pca data and returns a scikit-learn fitted KMeans object.

        Args:
            kmeans_k (int): Number of clusters. If not set, the optimal number of clusters is determined automatically.

        Returns:
            KMeans: Scikit-learn KMeans object that is fitted to self.pca_data.
        """
        pca_data_np = self.pc_vectors
        if kmeans_k is None:
            kmeans_k = self.get_optimal_kmeans_k()
        kmeans = KMeans(random_state=42, n_clusters=kmeans_k, n_init=10)
        kmeans.fit(pca_data_np)
        return kmeans


def check_smartpca_results(evec: pathlib.Path, eval: pathlib.Path):
    """
    Checks whether the smartpca results finished properly and contain all required information.

    Args:
        evec (pathlib.Path): Filepath pointing to a .evec result file of a smartpca run.
        eval (pathlib.Path): Filepath pointing to a .eval result file of a smartpca run.

    Returns: None

    Raises:
        PandoraException: If either the evec file or the eval file are incorrect.

    """
    # check the evec file:
    # - first line should start with #eigvals: and then determines the number of PCs
    with evec.open() as f:
        line = f.readline().strip()
        if not line.startswith("#eigvals"):
            raise PandoraException(
                f"SmartPCA evec result file appears to be incorrect: {evec}"
            )

        variances = line.split()[1:]
        try:
            [float(v) for v in variances]
        except ValueError:
            raise PandoraException(
                f"SmartPCA evec result file appears to be incorrect: {evec}"
            )
        n_pcs = len(variances)

        # all following lines should look like this:
        # SampleID  PC0  PC1  ...  PCN-1  Population
        for line in f.readlines():
            values = line.strip().split()
            if len(values) != n_pcs + 2:
                raise PandoraException(
                    f"SmartPCA evec result file appears to be incorrect: {evec}"
                )

            # all PC values should be floats
            try:
                [float(v) for v in values[1:-1]]
            except ValueError:
                raise PandoraException(
                    f"SmartPCA evec result file appears to be incorrect: {evec}"
                )

    # check the eval file: each line should cotain a single float only
    for line in eval.open():
        line = line.strip()
        try:
            float(line)
        except ValueError:
            raise PandoraException(
                f"SmartPCA eval result file appears to be incorrect: {eval}"
            )


def from_smartpca(evec: pathlib.Path, eval: pathlib.Path) -> PCA:
    """
    Creates a PCA object based on the results of a smartpca run

    Args:
        evec (pathlib.Path): Filepath pointing to a .evec result file of a smartpca run.
        eval (pathlib.Path): Filepath pointing to a .eval result file of a smartpca run.

    Returns:
        PCA: PCA object of the results of the respective smartpca run.

    Raises:
        PandoraException: If either the evec file or the eval file are incorrect.

    """
    # make sure both files are in correct format
    check_smartpca_results(evec, eval)
    # First, read the eigenvectors and transform it into the pca_data pandas dataframe
    with open(evec) as f:
        # first line does not contain data we are interested in
        f.readline()
        pca_data = pd.read_table(f, delimiter=" ", skipinitialspace=True, header=None)

    n_pcs = pca_data.shape[1] - 2

    cols = ["sample_id", *[f"PC{i}" for i in range(n_pcs)], "population"]
    pca_data = pca_data.rename(columns=dict(zip(pca_data.columns, cols)))
    pca_data = pca_data.sort_values(by="sample_id").reset_index(drop=True)

    # next, read the eigenvalues and compute the explained variances for all n_pcs principal components
    eigenvalues = open(eval).readlines()
    eigenvalues = [float(ev) for ev in eigenvalues]
    explained_variances = [ev / sum(eigenvalues) for ev in eigenvalues]
    # keep only the first n_pcs explained variances
    explained_variances = np.asarray(explained_variances[:n_pcs])

    return PCA(pca_data=pca_data, explained_variances=explained_variances, n_pcs=n_pcs)
