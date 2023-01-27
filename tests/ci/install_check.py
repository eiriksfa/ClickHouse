#!/usr/bin/env python3

import logging
import os
import sys
import subprocess
import atexit
from typing import List, Tuple

from github import Github

from build_download_helper import download_builds_filter
from clickhouse_helper import (
    ClickHouseHelper,
    mark_flaky_tests,
    prepare_tests_results_for_clickhouse,
)
from commit_status_helper import post_commit_status, update_mergeable_check
from docker_pull_helper import get_image_with_version
from env_helper import TEMP_PATH, REPORTS_PATH
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


def main():
    logging.basicConfig(level=logging.INFO)

    stopwatch = Stopwatch()

    check_name = sys.argv[1]

    if not os.path.exists(TEMP_PATH):
        os.makedirs(TEMP_PATH)

    pr_info = PRInfo()

    gh = Github(get_best_robot_token(), per_page=100)

    atexit.register(update_mergeable_check, gh, pr_info, check_name)

    rerun_helper = RerunHelper(gh, pr_info, check_name)
    if rerun_helper.is_already_finished_by_status():
        logging.info("Check is already finished according to github status, exiting")
        sys.exit(0)

    docker_images = {
        name: get_image_with_version(REPORTS_PATH, name)
        for name in (RPM_IMAGE, DEB_IMAGE)
    }

    def filter_artifacts(path: str) -> bool:
        return (
            path.endswith(".deb")
            or path.endswith(".rpm")
            or path.endswith(".tgz")
            or path.endswith("/clickhouse")
        )

    download_builds_filter(check_name, REPORTS_PATH, TEMP_PATH, filter_artifacts)

    run_command = (
        f"docker run --name=test-install "
        f"--cap-add=SYS_PTRACE --volume={REPORTS_PATH}:/packages {{docker_image}}"
    )

    return

    run_log_path = os.path.join(test_output, "run.log")

    logging.info("Going to run func tests: %s", run_command)

    with TeePopen(run_command, run_log_path) as process:
        retcode = process.wait()
        if retcode == 0:
            logging.info("Run successfully")
        else:
            logging.info("Run failed")

    subprocess.check_call(f"sudo chown -R ubuntu:ubuntu {TEMP_PATH}", shell=True)

    s3_helper = S3Helper()
    state, description, test_results, additional_logs = process_results(test_output)

    ch_helper = ClickHouseHelper()
    mark_flaky_tests(ch_helper, check_name, test_results)

    report_url = upload_results(
        s3_helper,
        pr_info.number,
        pr_info.sha,
        test_results,
        [run_log_path] + additional_logs,
        check_name,
    )
    print(f"::notice ::Report url: {report_url}")
    post_commit_status(gh, pr_info.sha, check_name, description, state, report_url)

    prepared_events = prepare_tests_results_for_clickhouse(
        pr_info,
        test_results,
        state,
        stopwatch.duration_seconds,
        stopwatch.start_time_str,
        report_url,
        check_name,
    )

    ch_helper.insert_events_into(db="default", table="checks", events=prepared_events)

    if state == "failure":
        sys.exit(1)


if __name__ == "__main__":
    main()
