"""
Numpy uses OMP and BLAS for its linear algebra under the hood. Per default, both libraries use all cores on the machine.
Since we are doing a pairwise comparison of all bootstrap/window replicates, for a substantial amount of time Pandora
would require all cores on the machine, which is not an option when working on shared servers/clusters.
Therefore, we set the OMP and BLAS threads manually to 1 to prevent this.
Setting these variables needs to happen before the first import of numpy.
"""
import os

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import argparse
import datetime
import math
import pathlib
import sys
import textwrap
import time

from pandora import __version__
from pandora.custom_errors import PandoraConfigException
from pandora.custom_types import AnalysisMode, FileFormat
from pandora.logger import SCRIPT_CLOCK_START, START_TIME, fmt_message, logger
from pandora.pandora import (
    Pandora,
    convert_to_eigenstrat_format,
    pandora_config_from_configfile,
)


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


@logger.catch
def main():
    print(get_header())
    logger.add(sys.stderr, format="{message}")
    args = argument_parser()

    """
    Pandora main program
    """
    # =======================================
    # initialize options and directories
    # =======================================
    pandora_config = pandora_config_from_configfile(args.config)

    # set the log verbosity according to the pandora config
    logger.remove()
    logger.add(sys.stderr, level=pandora_config.loglevel, format="{message}")

    # hook up the logfile to the logger to also store the output
    pandora_config.result_dir.mkdir(exist_ok=True, parents=True)
    pandora_config.pandora_logfile.open(mode="w").write(get_header())
    logger.add(
        pandora_config.pandora_logfile,
        level=pandora_config.loglevel,
        format="{message}",
    )

    # log program start and run configuration
    _start_time_str = START_TIME.strftime("%d-%b-%Y %H:%M:%S")
    logger.info(f"Pandora was called at {_start_time_str} as follows:\n")
    logger.info(" ".join(sys.argv))

    # log the run configuration
    _arguments_str = [
        f"{k}: {v}" for k, v in pandora_config.get_configuration().items()
    ]
    logger.info("\n--------- PANDORA CONFIGURATION ---------")
    logger.info("\n".join(_arguments_str))

    # store pandora config in a verbose config file for reproducibility
    pandora_config.save_config()

    # =======================================
    # start computation
    # =======================================
    logger.info("\n--------- STARTING COMPUTATION ---------")

    # if necessary, convert the input data to EIGENSTRAT file_format required for bootstrapping/windowing
    if pandora_config.file_format != FileFormat.EIGENSTRAT:
        logger.info(
            fmt_message(
                f"Converting dataset from {pandora_config.file_format.value} to {FileFormat.EIGENSTRAT.value}"
            )
        )
        pandora_config = convert_to_eigenstrat_format(pandora_config)

    # initialize empty Pandora object that keeps track of all results
    pandora_results = Pandora(pandora_config)

    # Run PCA/MDS on the input dataset without any bootstrapping or sliding-window
    pandora_results.embed_dataset()

    if pandora_config.analysis_mode == AnalysisMode.BOOTSTRAP:
        pandora_results.bootstrap_embeddings()
    elif pandora_config.analysis_mode == AnalysisMode.SLIDING_WINDOW:
        pandora_results.sliding_window()
    else:
        raise PandoraConfigException(
            f"Unrecognized Analaysis mode: {pandora_config.analysis_mode.value}"
        )

    logger.info("\n\n========= PANDORA RESULTS =========")
    logger.info(f"> Input dataset: {pandora_config.dataset_prefix.absolute()}")

    pandora_results.log_and_save_replicates_results()

    pandora_config.log_results_files()

    total_runtime = math.ceil(time.perf_counter() - SCRIPT_CLOCK_START)
    logger.info(
        f"\nTotal runtime: {datetime.timedelta(seconds=total_runtime)} ({total_runtime} seconds)"
    )


if __name__ == "__main__":
    main()
