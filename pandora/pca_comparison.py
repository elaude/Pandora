from __future__ import (
    annotations,
)  # allows type hint PCAComparison inside PCAComparison class

import warnings

import pandas as pd
from scipy.spatial import procrustes
from sklearn.metrics import fowlkes_mallows_score
from sklearn.metrics.pairwise import euclidean_distances

from pandora.custom_types import *
from pandora.custom_errors import *
from pandora.pca import PCA


def filter_samples(pca: PCA, samples_to_keep: List[str]) -> PCA:
    """
    Filters the given PCA by removing all samples not contained in samples_to_keep

    Args:
        pca (PCA): PCA object to filter.
        samples_to_keep (List[str]): List of sample IDs to keep.

    Returns: new PCA object containing the data of pca for all samples in samples_to_keep

    """
    pca_data = pca.pca_data
    pca_data = pca_data.loc[pca_data.sample_id.isin(samples_to_keep)]

    return PCA(
        pca_data=pca_data, explained_variances=pca.explained_variances, n_pcs=pca.n_pcs
    )


def _check_sample_clipping(before_clipping: PCA, after_clipping: PCA) -> None:
    """
    Compares the number of samples prior to and after clipping. Will show a warning message in case more
    than 20% of samples were removed, indicating a potential major mismatch between the two PCAs.

    Args:
        before_clipping (PCA): PCA object prior to sample filtering.
        after_clipping (PCA): PCA object after sample filtering.

    Returns: None

    """
    n_samples_before = before_clipping.pca_data.shape[0]
    n_samples_after = after_clipping.pca_data.shape[0]

    if n_samples_after <= 0.8 * n_samples_before:
        warnings.warn(
            "More than 20% of samples were removed for the comparison. "
            "Your data appears to have lots of outliers. "
            f"#Samples before/after clipping: {n_samples_before}/{n_samples_after} ",
        )


def _clip_missing_samples_for_comparison(
    comparable: PCA, reference: PCA
) -> Tuple[PCA, PCA]:
    """
    Reduces comparable and reference to similar sample IDs to make sure we compare projections for identical samples.

    Args:
        comparable (PCA): first PCA object to compare
        reference (PCA): second PCA object to compare

    Returns:
        (PCA, PCA): Comparable and reference PCAs containing only the samples present in both PCAs.

    """
    comp_data = comparable.pca_data
    ref_data = reference.pca_data

    comp_ids = set(comp_data.sample_id)
    ref_ids = set(ref_data.sample_id)

    shared_samples = sorted(comp_ids.intersection(ref_ids))

    comparable_clipped = filter_samples(comparable, shared_samples)
    reference_clipped = filter_samples(reference, shared_samples)

    assert comparable_clipped.pc_vectors.shape == reference_clipped.pc_vectors.shape
    # Issue a warning if we clip more than 20% of all samples of either PCA
    # and fail if there are no samples lef
    _check_sample_clipping(comparable, comparable_clipped)
    _check_sample_clipping(reference, reference_clipped)

    return comparable_clipped, reference_clipped


class PCAComparison:
    """Class structure for comparing two PCA results.

    This class provides methods for comparing both PCAs based on all samples,
    for comparing the K-Means clustering results, and for computing sample support values.

    Prior to comparing the results, both PCAs are filtered such that they only contain samples present in both PCAs.

    Note that for comparing PCA results, the sample IDs are used to ensure the correct comparison of projections.
    If an error occurs during initialization, this is most likely due to incorrect sample IDs.

    Attributes:
        comparable (PCA): comparable PCA object after sample filtering and Procrustes Transformation.
        reference (PCA): reference PCA object after sample filtering and Procrustes Transformation.
        sample_ids (pd.Series[str]): pd.Series containing the sample IDs present in both PCA objects
    """

    def __init__(self, comparable: PCA, reference: PCA):
        """
        Initializes a new PCAComparison object using comparable and reference.
        On initialization, comparable and reference are both reduced to contain only samples present in both PCAs.
        In order to compare the two PCAs, on initialization Procrustes Analysis is applied transforming
        comparable towards reference. Procrustes Analysis transforms comparable by applying scaling, translation,
        rotation and reflection aiming to match all sample projections as close as possible to the projections in
        reference.

        Args:
            comparable: PCA object to compare.
            reference: PCA object to transform comparable towards.
        """

        self.comparable, self.reference, self.disparity = match_and_transform(
            comparable=comparable, reference=reference
        )
        self.sample_ids = self.comparable.pca_data.sample_id

    def compare(self) -> float:
        """
        Compares self.comparable to self.reference using Procrustes Analysis and returns the similarity.

        Returns:
            float: Similarity score on a scale of 0 (entirely different) to 1 (identical) measuring the similarity of
                self.comparable and self.reference.

        """
        similarity = np.sqrt(1 - self.disparity)

        return similarity

    def compare_clustering(self, kmeans_k: int = None) -> float:
        """
        Compares the assigned cluster labels based on K-Means clustering on self.reference and self.comparable.

        Args:
            kmeans_k (int): Number k of clusters to use for K-Means clustering.
                If not set, the optimal number of clusters is determined automatically using self.reference.

        Returns:
            float: The Fowlkes-Mallow score of Cluster similarity between the clustering results
                of self.reference and self.comparable. The score ranges from 0 (entirely distinct) to 1 (identical).
        """
        if kmeans_k is None:
            # we are comparing self to other -> use other as ground truth
            # thus, we determine the number of clusters using other
            kmeans_k = self.reference.get_optimal_kmeans_k()

        # since we are only comparing the assigned cluster labels, we don't need to transform self prior to comparing
        comp_kmeans = self.comparable.cluster(kmeans_k=kmeans_k)
        ref_kmeans = self.reference.cluster(kmeans_k=kmeans_k)

        comp_cluster_labels = comp_kmeans.predict(self.comparable.pc_vectors)
        ref_cluster_labels = ref_kmeans.predict(self.reference.pc_vectors)

        return fowlkes_mallows_score(ref_cluster_labels, comp_cluster_labels)

    def _get_sample_distances(self) -> pd.Series[float]:
        """
        Computest the euclidean distances between pairs of samples in self.reference and self.comparable.

        Returns:
            pd.Series[float]: Euclidean distance between projections for each sample in
                self.reference and self.comparable. Contains one value for each sample in self.sample_ids

        """
        # make sure we are comparing the correct PC-vectors in the following
        assert np.all(
            self.comparable.pca_data.sample_id == self.reference.pca_data.sample_id
        )

        sample_distances = euclidean_distances(
            self.reference.pc_vectors, self.comparable.pc_vectors
        ).diagonal()
        return pd.Series(sample_distances, index=self.sample_ids)

    def get_sample_support_values(self) -> pd.Series[float]:
        """
        Computes the samples support value for each sample in self.sample_id using the euclidean distance
        between projections in self.reference and self.comparable.
        The euclidean distance `d` is normalized to [0, 1] by computing ` 1 / (1 + d)`.
        The higher the support the closer the projections are in euclidean space in self.reference and self.comparable.

        Returns:
            pd.Series[float]: Support value when comparing self.reference and self.comparable for each sample in self.sample_id

        """
        sample_distances = self._get_sample_distances()
        support_values = 1 / (1 + sample_distances)
        return support_values

    def detect_rogue_samples(
        self, support_value_rogue_cutoff: float = 0.5
    ) -> pd.Series[float]:
        """
        Returns the support values for all samples with a support value below support_value_rogue_cutoff.

        Args:
            support_value_rogue_cutoff (float): Threshold flagging samples as rogue. Default is 0.5.

        Returns:
            pd.Series[float]: Support values for all samples with a support value below support_value_rogue_cutoff.
                The indices of the pandas Series correspond to the sample IDs.

        """
        support_values = self.get_sample_support_values()

        rogue = support_values.loc[lambda x: (x.support < support_value_rogue_cutoff)]

        return rogue


def _numpy_to_pca_dataframe(
    pc_vectors: npt.NDArray[float],
    sample_ids: pd.Series[str],
    populations: pd.Series[str],
):
    """
    Transforms a numpy ndarray to a pandas Dataframe as required for initializing a PCA object.

    Args:
        pc_vectors (npt.NDArray[float]): Numpy ndarray containing the PCA results (PC vectors) for all samples.
        sample_ids (pd.Series[str]): Pandas Series containing the sample IDs corresponding to the pc_vectors.
        populations (pd.Series[str]): Pandas Series containing the populations corresponding to the sample_ids.

    Returns:
        pd.DataFrame: Pandas dataframe containing all required columns to initialize a PCA object
            (sample_id, population, PC{i} for i in range(pc_vectors.shape[1]))

    """
    if pc_vectors.ndim != 2:
        raise PandoraException(
            f"Numpy PCA data must be two dimensional. Passed data has {pc_vectors.ndim} dimensions."
        )

    pca_data = pd.DataFrame(
        pc_vectors, columns=[f"PC{i}" for i in range(pc_vectors.shape[1])]
    )

    if sample_ids.shape[0] != pca_data.shape[0]:
        raise PandoraException(
            f"One sample ID required for each sample. Got {len(sample_ids)} IDs, "
            f"but pca_data has {pca_data.shape[0]} samples."
        )

    pca_data["sample_id"] = sample_ids.values

    if populations.shape[0] != pca_data.shape[0]:
        raise PandoraException(
            f"One population required for each sample. Got {len(populations)} populations, "
            f"but pca_data has {pca_data.shape[0]} samples."
        )

    pca_data["population"] = populations.values
    return pca_data


def match_and_transform(comparable: PCA, reference: PCA) -> Tuple[PCA, PCA, float]:
    """
    Uses Procrustes Analysis to find a transformation matrix that most closely matches comparable to reference.
    and transforms comparable.

    Args:
        comparable (PCA): The PCA that should be transformed
        reference (PCA): The PCA that comparable should be transformed towards

    Returns:
        Tuple[PCA, PCA, float]: Two new PCA objects and the disparity. The first new PCA is the transformed comparable
            and the second one is the standardized reference. The disparity is the sum of squared distances between the
            transformed comparable and transformed reference PCAs.

    Raises:
        PandoraException:
            - Mismatch in sample IDs between comparable and reference (identical sample IDs required for comparison)
            - No samples left after clipping. This is most likely caused by incorrect annotations of sample IDs.
    """
    comparable, reference = _clip_missing_samples_for_comparison(comparable, reference)

    if not all(comparable.pca_data.sample_id == reference.pca_data.sample_id):
        raise PandoraException(
            "Sample IDS between reference and comparable don't match but is required for comparing PCA results. "
        )

    comp_data = comparable.pc_vectors
    ref_data = reference.pc_vectors

    if comp_data.shape != ref_data.shape:
        raise PandoraException(
            f"Number of samples or PCs in comparable and reference do not match. "
            f"Got {comp_data.shape} and {ref_data.shape} respectively."
        )

    if comp_data.shape[0] == 0:
        raise PandoraException(
            "No samples left for comparison after clipping. "
            "Make sure all sample IDs are correctly annotated"
        )

    standardized_reference, transformed_comparable, disparity = procrustes(
        ref_data, comp_data
    )

    standardized_reference = _numpy_to_pca_dataframe(
        standardized_reference,
        reference.pca_data.sample_id,
        reference.pca_data.population,
    )

    standardized_reference = PCA(
        pca_data=standardized_reference,
        explained_variances=reference.explained_variances,
        n_pcs=reference.n_pcs,
    )

    transformed_comparable = _numpy_to_pca_dataframe(
        transformed_comparable,
        comparable.pca_data.sample_id,
        comparable.pca_data.population,
    )

    transformed_comparable = PCA(
        pca_data=transformed_comparable,
        explained_variances=comparable.explained_variances,
        n_pcs=comparable.n_pcs,
    )

    if not all(
        standardized_reference.pca_data.sample_id
        == transformed_comparable.pca_data.sample_id
    ):
        raise PandoraException(
            "Sample IDS between reference and comparable don't match but is required for comparing PCA results. "
        )

    return standardized_reference, transformed_comparable, disparity
