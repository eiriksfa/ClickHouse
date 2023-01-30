#!/usr/bin/env python3

import argparse

# import atexit
import logging
import sys
import subprocess
from pathlib import Path

# from typing import List, Tuple

from github import Github

from build_download_helper import download_builds_filter
from clickhouse_helper import (
    ClickHouseHelper,
    mark_flaky_tests,
    prepare_tests_results_for_clickhouse,
)
from commit_status_helper import post_commit_status  # , update_mergeable_check
from docker_pull_helper import get_image_with_version, DockerImage
from env_helper import TEMP_PATH as TEMP, REPORTS_PATH
from get_robot_token import get_best_robot_token
from pr_info import PRInfo
from report import TestResults, TestResult
from rerun_helper import RerunHelper
from s3_helper import S3Helper
from stopwatch import Stopwatch
from tee_popen import TeePopen
from upload_result_helper import upload_results


RPM_IMAGE = "clickhouse/install-rpm-test"
DEB_IMAGE = "clickhouse/install-deb-test"
TEMP_PATH = Path(TEMP)
SUCCESS = "success"
FAILURE = "failure"


def test_install_deb(image: DockerImage) -> TestResults:
    tests = {
        "Install server deb": r"""apt-get install /packages/clickhouse-{server,client,common}*deb
systemctl start clickhouse-server
clickhouse-client -q 'SELECT version()'""",
        "Install keeper deb": r"""apt-get install /packages/clickhouse-keeper*deb
systemctl start clickhouse-keeper
for i in {1..20}; do
    echo wait for clickhouse-keeper to being up
    > /dev/tcp/127.0.0.1/9181 2>/dev/null || sleep 1
done
exec 13<>/dev/tcp/127.0.0.1/9181
echo mntr >&13
cat <&13 | grep zk_version""",
    }
    test_results = []  # type: TestResults
    for name, command in tests.items():
        test_results.append(test_install(name, command, image))

    return test_results


def test_install(test_name: str, command: str, image: DockerImage) -> TestResult:
    stopwatch = Stopwatch()
    container_name = test_name.lower().replace(" ", "_")
    log_file = TEMP_PATH / f"{container_name}.log"
    run_command = (
        f"docker run --name={container_name} --detach --cap-add=SYS_PTRACE "
        f"--rm --privileged --volume={TEMP_PATH}:/packages {image}"
    )
    subprocess.call(f"docker kill {container_name}", shell=True)
    logging.info("Running docker container: `%s`", run_command)
    subprocess.check_call(run_command, shell=True)
    script_file = TEMP_PATH / "install.sh"
    script_file.write_text(command)
    install_command = f"docker exec {container_name} bash -ex /packages/install.sh"
    with TeePopen(install_command, log_file) as process:
        retcode = process.wait()
        if retcode == 0:
            status = SUCCESS
        else:
            status = FAILURE

    subprocess.check_call(f"docker kill {container_name}", shell=True)
    return TestResult(test_name, status, stopwatch.duration_seconds, [log_file])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Script to release a new ClickHouse version, requires `git` and "
        "`gh` (github-cli) commands "
        "!!! LAUNCH IT ONLY FROM THE MASTER BRANCH !!!",
    )

    parser.add_argument(
        "check_name",
        help="check name, used to download the packages",
    )
    parser.add_argument(
        "--no-download",
        dest="download",
        action="store_false",
        default=argparse.SUPPRESS,
        help="if set, the packages won't be downloaded, useful for debug",
    )

    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO)

    stopwatch = Stopwatch()

    args = parse_args()

    TEMP_PATH.mkdir(parents=True, exist_ok=True)

    pr_info = PRInfo()

    gh = Github(get_best_robot_token(), per_page=100)

    # atexit.register(update_mergeable_check, gh, pr_info, args.check_name)

    rerun_helper = RerunHelper(gh, pr_info, args.check_name)
    if rerun_helper.is_already_finished_by_status():
        logging.info("Check is already finished according to github status, exiting")
        sys.exit(0)

    docker_images = {
        name: get_image_with_version(REPORTS_PATH, name)
        for name in (RPM_IMAGE, DEB_IMAGE)
    }

    if args.download:

        def filter_artifacts(path: str) -> bool:
            return (
                path.endswith(".deb")
                or path.endswith(".rpm")
                or path.endswith(".tgz")
                or path.endswith("/clickhouse")
            )

        download_builds_filter(
            args.check_name, REPORTS_PATH, TEMP_PATH, filter_artifacts
        )

    test_results = test_install_deb(docker_images[DEB_IMAGE])

    return

    print()  # pylint:disable=unreachable

    state = SUCCESS
    if FAILURE in (result.status for result in test_results):
        state = FAILURE

    s3_helper = S3Helper()

    ch_helper = ClickHouseHelper()
    mark_flaky_tests(ch_helper, args.check_name, test_results)

    report_url = upload_results(
        s3_helper,
        pr_info.number,
        pr_info.sha,
        test_results,
        [],
        args.check_name,
    )
    print(f"::notice ::Report url: {report_url}")
    description = f"Packages installation test: {state}"
    post_commit_status(gh, pr_info.sha, args.check_name, description, state, report_url)

    prepared_events = prepare_tests_results_for_clickhouse(
        pr_info,
        test_results,
        state,
        stopwatch.duration_seconds,
        stopwatch.start_time_str,
        report_url,
        args.check_name,
    )

    ch_helper.insert_events_into(db="default", table="checks", events=prepared_events)

    if state == FAILURE:
        sys.exit(1)


if __name__ == "__main__":
    main()
