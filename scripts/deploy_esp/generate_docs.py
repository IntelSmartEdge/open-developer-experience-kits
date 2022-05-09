#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2022 Intel Corporation

"""
This script generates viewable html documentation from provided markdown files.

Target audience are end customers deploying Experience Kits in offline mode.

Script was written for Python 3.6+ and uses no external dependencies, except for markdown.

This script can be run standalone or as part of generation of offline package proccess.

Available script options. Generate offline documentation:
 - default script invocation, input path has to be specified, output path is ./tmp:     <script> <input_path>
 - script run with input and output paths specified:            <script> <input_path> --output <output_path>
 - force option if output path folder has to be regenerated:    <script> <input_path> --output <output_path> --force
"""

import argparse
import logging
import os
import pathlib
import sys
import traceback

import re
import shutil

import seo.error

try:
    # E0401: Unable to import 'markdown' (import-error)
    # 'disable' was added to work around the lack of a markdown library on jenkins
    # pylint: disable=E0401
    import markdown
except ModuleNotFoundError:
    sys.stderr.write(
        "ERROR: Couldn't import markdown module.\n"
        "   It can be installed using following command:\n"
        "   $ pip3 install markdown\n")
    sys.exit(seo.error.Codes.MISSING_PREREQUISITE.value)


def parse_args():
    """ Parse script arguments """

    p = argparse.ArgumentParser(
        description="""Start Smart Edge offline docs package creation proccess.""")

    p.add_argument(
        action="store", dest="in_path", metavar="input PATH", type=pathlib.Path,
        help="Path to folder containing input documentation which should be made available offline.")
    p.add_argument(
        "-o", "--output", action="store", dest="out_path", metavar="output PATH", type=pathlib.Path,
        default="./tmp",
        help="Path to folder containing generated output offline documentation.")
    p.add_argument(
        "-f", "--force", action="store_true", dest="force",
        help="If this option is provided then the output directory will be recreated.")
    p.add_argument(
        "--debug", action="store_true", dest="debug",
        help="Provide more verbose diagnostic information")

    return p.parse_args()


def check_preconditions(args):
    """ Check script's preconditions """

    logging.info("1/4 Checking preconditions")

    if not args.in_path.exists():
        raise seo.error.AppException(
            seo.error.Codes.MISSING_PREREQUISITE,
            f"Documentation input path does not exist in expected location '{args.in_path}'")

    if args.force and args.out_path.exists():
        shutil.rmtree(args.out_path)
        logging.warning("%s directory was deleted and new documentation will be created.", args.out_path)

    if args.out_path.exists():
        raise seo.error.AppException(
            seo.error.Codes.ARGUMENT_ERROR,
            f"""Documentation output path exists in location '{args.out_path}',
                if you want to regenerate documentation use -f/--force flag.""")


def find_files(cfg, path, filetype):
    """ Find files of certain filetype and return their filepaths and filenames """

    excluded_files = cfg["excluded_files"]

    file_paths = []

    for root, _, files in os.walk(path):
        for file_name in files:
            if file_name.endswith(filetype):
                if file_name in excluded_files:
                    continue

                file_paths.append((root.split(str(path))[1][1:], file_name))

    return file_paths


def copy_md_files(cfg, paths):
    """ Copy markdown files to docs folder """

    in_path = cfg["in_path"]
    out_path = cfg["out_path"]

    logging.info("3/4 Creating split md files.")

    for file_path, file_name in paths:
        os.makedirs(os.path.join(out_path, "input", file_path), exist_ok=True)
        os.makedirs(os.path.join(out_path, "split", file_path), exist_ok=True)
        os.makedirs(os.path.join(out_path, "html", "input", file_path), exist_ok=True)
        os.makedirs(os.path.join(out_path, "html", "split", file_path), exist_ok=True)

        src = os.path.join(in_path, file_path, file_name)
        dst = os.path.join(out_path, "input", file_path, file_name)

        try:
            shutil.copy(src, dst)
        except IOError as e:
            print(f"Unable to copy file. {e}")

    shutil.copy(os.path.dirname(__file__)+"/style.css", os.path.join(out_path, "html"))


def create_html_from_md(cfg):
    """Creation of webpages from md files."""

    logging.info("4/4 Creating html files.")

    out_path = cfg["out_path"]

    md_files = find_files(cfg, cfg["out_path"], ".md")
    # This section goes through 'input' and 'split' directories collecting md files
    # and creating html files in mirrored structure inside of 'html' dir.
    for path, file_name in md_files:
        with open(os.path.join(out_path, path, file_name), 'r') as f:
            md_content = f.read()

            # Title of html and path to the css file.
            css_file = os.path.relpath(os.path.join("style.css"), os.path.relpath(path))
            html5_template = f"<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\
                            \n<title>{file_name[:-3]}</title>\n<link rel=\"stylesheet\"href=\"{css_file}\">\
                            \n</head>\n<body>\n"

            html_content_from_md = markdown.markdown(md_content, extensions=['fenced_code'])
            if "split" in path:
                with open(os.path.join(out_path, "html", path, file_name[:-3] + ".html"), 'w') as f:
                    # 'split' and 'input' directories are mirrored structures,
                    # 'split' contains articles separated by tags into files
                    # 'input' contains entire html files which are needed for generating hyperlinks in html footer
                    split_to_input = path.replace("split", "input")
                    # Creation of relative path from split dir to input dir.
                    mainpage_file_path = os.path.relpath(os.path.relpath(os.path.join("html", split_to_input)),
                                                         os.path.relpath(os.path.join("html", path)))
                    mainpage_file_path = os.path.join(mainpage_file_path,
                                                      (re.search(r"^[^_]*", file_name).group()  + ".html"))
                    footer = f"\nVisit <a href=\"{mainpage_file_path}\">Main page</a> for more information."
                    f.write(html5_template + html_content_from_md + footer + "\n</body>\n</html>")
            else:
                with open(os.path.join(out_path, "html", path, file_name[:-3] + ".html"), 'w') as f:
                    f.write(html5_template + html_content_from_md + "\n</body>\n</html>")


def get_md_sections(cfg, file_path, file_name):
    """ Split Markdown file to separate sections """

    out_path = cfg["out_path"]

    lines = []
    sections = []
    tag = ""

    tags = []

    with open(os.path.join(out_path, "input", file_path, file_name), 'r') as md_file:
        for line in md_file:

            if re.match(r"^(?=#{1,6})(.*)(?= +<a)", line):
                if tag:
                    sections.append((tag[:], lines[:]))
                    lines.clear()

                tag = str.lower(re.findall(r'(?=(SEO))(.*)(?=(("|\')(.*)>))', line)[0][1]).replace('-', "_")
                tags.append(tag)

                line = re.sub(r"(?= <a)(.*)(?=$)", "", line)

            if tag:
                lines.append(line)

        # add last section when all lines read
        if lines:
            sections.append((tag[:], lines[:]))
            lines.clear()

    return sections, tags


def write_md_sections(cfg, sections, file_path, file_name):
    """ Write splitted Markdown files """

    out_path = cfg["out_path"]

    for tag, lines in sections:
        with open(os.path.join(out_path, "split", file_path, file_name[:-3] + "_" + tag + ".md"), "w") as f:
            f.writelines(lines)


def split_md_files(cfg, paths):
    """ Split markdown files according to sections """

    unique_tags = []

    for file_path, file_name in paths:
        sections, tags = get_md_sections(cfg, file_path, file_name)

        unique_tags.extend(tags)

        if len(unique_tags) != len(set(unique_tags)):
            raise seo.error.AppException(
                seo.error.Codes.RUNTIME_ERROR,
                f"A duplicate of article id was detected in the file {file_name}.")

        write_md_sections(cfg, sections, file_path, file_name)


def run_main():
    """ Top level script entry function """

    args = parse_args()

    if args.debug:
        log_level = logging.DEBUG
        log_format = '%(asctime)s.%(msecs)03d %(levelname)s: %(message)s'
    else:
        log_level = logging.INFO
        log_format = '%(levelname)s: %(message)s'

    logging.basicConfig(level=log_level, format=log_format, datefmt='%Y-%m-%d %H:%M:%S')

    try:
        sys.exit(main(args).value)
    except seo.error.AppException as e:  # pylint: disable=invalid-name
        if args.debug:
            traceback.print_exc(file=sys.stderr)
        logging.error(e.code if e.msg is None else e.msg)
        sys.exit(e.code.value)


def main(args):
    """ Internal main function """

    check_preconditions(args)

    ex_files = ["PULL_REQUEST_TEMPLATE.md"]
    cfg = {"in_path": args.in_path, "out_path": args.out_path, "excluded_files": ex_files}

    logging.info("2/4 Looking for Markdown files located in input path.")
    md_files = find_files(cfg, cfg["in_path"], ".md")

    copy_md_files(cfg, md_files)
    split_md_files(cfg, md_files)
    create_html_from_md(cfg)

    logging.info("HTML files are located in %s.", os.path.join(cfg["out_path"], "html"))

    return seo.error.Codes.NO_ERROR


if __name__ == "__main__":
    run_main()
