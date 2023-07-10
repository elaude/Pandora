"""
Numpy uses OMP and BLAS for its linear algebra under the hood. Per default, both libraries use all cores on the machine.
Since we are doing a pairwise comparison of all bootstrap replicates, for a substantial amount of time Pandora would
require all cores on the machine, which is not an option when working on shared servers/clusters.
Therefore, we set the OMP and BLAS threads manually to 1 to prevent this.
Setting these variables needs to happen before the first import of numpy.
"""
import os

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import argparse
import datetime
import sys
import math

from pandora import __version__
from pandora.pandora import *
from pandora.logger import *


def get_header():
    return textwrap.dedent(
        f"Pandora version {__version__} released by The Exelixis Lab\n"
        f"Developed by: Julia Haag\n"
        f"Latest version: https://github.com/tschuelia/Pandora\n"
        f"Questions/problems/suggestions? Please open an issue on GitHub.\n",
    )


def argument_parser():
    parser = argparse.ArgumentParser(
        prog="Pandora", description="Command line parser for Pandora options."
    )
    parser.add_argument(
        "-c",
        "--config",
        type=pathlib.Path,
        required=True,
        help="Path to the yaml config file to use for the Pandora analyses. "
        "Needs to be in valid yaml file_format. See the example file for guidance on how to configure your run.",
    )

    return parser.parse_args()


def main():
    print(get_header())
    args = argument_parser()

    """
    Pandora main program
    """
    # =======================================
    # initialize options and directories
    # =======================================
    pandora_config = pandora_config_from_configfile(args.config)

    # TODO: compare pandora_config with potentially existing config file and warn user if settings changed but redo was not set

    # set the log verbosity according to the pandora config
    logger.setLevel(pandora_config.loglevel)

    # hook up the logfile to the logger to also store the output
    pandora_config.pandora_logfile.open(mode="w").write(get_header())
    logger.addHandler(logging.FileHandler(pandora_config.pandora_logfile))

    # log the run configuration
    _arguments_str = [
        f"{k}: {v}" for k, v in pandora_config.get_configuration().items()
    ]
    _command_line = " ".join(sys.argv)

    logger.info("--------- PANDORA CONFIGURATION ---------")
    logger.info("\n".join(_arguments_str))
    logger.info(f"\nCommand line: {_command_line}")

    # store pandora config in a verbose config file for reproducibility
    pandora_config.save_config()

    # =======================================
    # start computation
    # =======================================
    logger.info("\n--------- STARTING COMPUTATION ---------")

    # if necessary, convert the input data to EIGENSTRAT file_format required for bootstrapping
    if pandora_config.file_format != FileFormat.EIGENSTRAT:
        pandora_config.convert_to_eigenstrat_format()

    # initialize empty Pandora object that keeps track of all results
    pandora_results = Pandora(pandora_config)

    # TODO: implement alternative MDS analysis
    # Run PCA on the input dataset without any bootstrapping
    pandora_results.do_pca()

    if pandora_config.do_bootstrapping:
        # Bootstrapped PCAs
        pandora_results.bootstrap_pcas()

    logger.info("\n\n========= PANDORA RESULTS =========")
    logger.info(f"> Input dataset: {pandora_config.dataset_prefix.absolute()}")

    if pandora_config.do_bootstrapping:
        pandora_results.log_and_save_bootstrap_results()
        pandora_results.log_and_save_sample_support_values()

    pandora_config.log_results_files()

    total_runtime = math.ceil(time.perf_counter() - SCRIPT_START)
    logger.info(
        f"\nTotal runtime: {datetime.timedelta(seconds=total_runtime)} ({total_runtime} seconds)"
    )


if __name__ == "__main__":
    main()
