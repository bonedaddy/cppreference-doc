#!/usr/bin/env python3

#   Copyright (C) 2011, 2012  Povilas Kanapickas <povilas@radix.lt>
#
#   This file is part of cppreference-doc
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see http://www.gnu.org/licenses/.

import argparse
import fnmatch
from lxml import etree
import re
import os
import sys
import shutil
import urllib.parse
from xml_utils import xml_escape, xml_unescape

def rmtree_if_exists(dir):
    if os.path.isdir(dir):
        shutil.rmtree(dir)

def move_dir_contents_to_dir(srcdir, dstdir):
    for fn in os.listdir(srcdir):
        shutil.move(os.path.join(srcdir, fn),
                    os.path.join(dstdir, fn))

def rearrange_archive(root):
    # rearrange the archive. {root} here is output/reference

    # before
    # {root}/en.cppreference.com/w/ : html
    # {root}/en.cppreference.com/mwiki/ : data
    # {root}/en.cppreference.com/ : data
    # ... (other languages)
    # {root}/upload.cppreference.com/mwiki/ : data

    # after
    # {root}/common/ : all common data
    # {root}/en/ : html for en
    # ... (other languages)

    data_path = os.path.join(root, 'common')
    rmtree_if_exists(data_path)
    shutil.move(os.path.join(root, 'upload.cppreference.com/mwiki'), data_path)
    shutil.rmtree(os.path.join(root, 'upload.cppreference.com'))

    for lang in ["en"]:
        path = os.path.join(root, lang + ".cppreference.com/")
        src_html_path = path + "w/"
        src_data_path = path + "mwiki/"
        html_path = os.path.join(root, lang)

        if os.path.isdir(src_html_path):
            shutil.move(src_html_path, html_path)

        if os.path.isdir(src_data_path):
            # the skin files should be the same for all languages thus we
            # can merge everything
            move_dir_contents_to_dir(src_data_path, data_path)

        # also copy the custom fonts
        shutil.copy(os.path.join(path, 'DejaVuSansMonoCondensed60.ttf'), data_path)
        shutil.copy(os.path.join(path, 'DejaVuSansMonoCondensed75.ttf'), data_path)

        # remove what's left
        shutil.rmtree(path)

# strip query strings from filenames to support Windows filesystems.
def add_file_to_rename_map(rename_map, dir, fn, new_fn):
    path = os.path.join(dir, fn)
    if not os.path.isfile(path):
        print("Not renaming " + path)
        return
    rename_map.append((dir, fn, new_fn))

def find_files_to_be_renamed(root):
    # returns a rename map: array of tuples each of which contain three strings:
    # the directory the file resides in, the source and destination filenames
    rename_map = []

    files_rename_qs = []        # remove query string
    files_rename_quot = []      # remove quotes
    files_loader = []           # files served by load.php
    for dir, dirnames, filenames in os.walk(root):
        for filename in fnmatch.filter(filenames, '*[?]*'):
            files_rename_qs.append((dir, filename))
        for filename in fnmatch.filter(filenames, '*"*'):
            files_rename_quot.append((dir, filename))
        for filename in fnmatch.filter(filenames, 'load.php[?]*'):
            files_loader.append((dir, filename))

    for dir,fn in files_loader:
        files_rename_qs.remove((dir, fn))

    for dir,fn in files_rename_qs:
        add_file_to_rename_map(rename_map, dir, fn, re.sub('\?.*', '', fn))
    for dir,fn in files_rename_quot:
        add_file_to_rename_map(rename_map, dir, fn, re.sub('"', '_q_', fn))

    # map loader names to more recognizable names
    for dir,fn in files_loader:
        if re.search("modules=site&only=scripts", fn):
            new_fn = "site_scripts.js"
        elif re.search("modules=site&only=styles", fn):
            new_fn = "site_modules.css"
        elif re.search("modules=skins.*&only=scripts", fn):
            new_fn = "skin_scripts.js"
        elif re.search("modules=startup&only=scripts", fn):
            new_fn = "startup_scripts.js"
        elif re.search("modules=.*ext.*&only=styles", fn):
            new_fn = "ext.css"
        else:
            print("Loader file " + fn + " does not match any known files")
            sys.exit(1)

        add_file_to_rename_map(rename_map, dir, fn, new_fn)

    # rename filenames that conflict on case-insensitive filesystems
    # TODO: perform this automatically
    add_file_to_rename_map(rename_map, os.path.join(root, 'en/cpp/numeric/math'), 'NAN.html', 'NAN.2.html')
    add_file_to_rename_map(rename_map, os.path.join(root, 'en/c/numeric/math'), 'NAN.html', 'NAN.2.html')
    return rename_map

def rename_files(rename_map):
    for dir, old_fn, new_fn in rename_map:
        shutil.move(os.path.join(dir, old_fn), os.path.join(dir, new_fn))

def find_html_files(root):
    # find files that need to be preprocessed
    html_files = []
    for dir, dirnames, filenames in os.walk(root):
        for filename in fnmatch.filter(filenames, '*.html'):
            html_files.append(os.path.join(dir, filename))
    return html_files

def fix_relative_link(rename_map, target):
    if 'http://' in target or 'https://' in target:
        return target

    target = urllib.parse.unquote(target)
    for dir,fn,new_fn in rename_map:
        target = target.replace(fn, new_fn)
    target = target.replace('../../upload.cppreference.com/mwiki/','../common/')
    target = target.replace('../mwiki/','../common/')
    target = re.sub('(\.php|\.css)\?.*', '\\1', target)
    target = urllib.parse.quote(target)
    target = target.replace('%23', '#')
    return target

def has_class(el, classes_to_check):
    value = el.get('class')
    if value is None:
        return False
    classes = value.split(' ')
    for cl in classes_to_check:
        if cl in classes:
            return True
    return False

def preprocess_html_file(root, fn, rename_map):
    parser = etree.HTMLParser()
    html = etree.parse(fn, parser)

    # remove non-printable elements
    for el in html.xpath('//*'):
        if has_class(el, ['noprint', 'editsection']):
            el.getparent().remove(el)
        if el.get('id') == 'toc':
            el.getparent().remove(el)

    # remove external links to unused resources
    for el in html.xpath('/html/head/link'):
        if el.get('rel') in [ 'alternate', 'search', 'edit', 'EditURI' ]:
            el.getparent().remove(el)

    # remove Google Analytics scripts
    for el in html.xpath('/html/body/script'):
        if el.get('src') is not None and 'google-analytics.com/ga.js' in el.get('src'):
            el.getparent().remove(el)
        elif el.text is not None and ('google-analytics.com/ga.js' in el.text or 'pageTracker' in el.text):
            el.getparent().remove(el)

    # apply changes to links caused by file renames
    for el in html.xpath('//*[@src or @href]'):
        if el.get('src') is not None:
            el.set('src', fix_relative_link(rename_map, el.get('src')))
        elif el.get('href') is not None:
            el.set('href', fix_relative_link(rename_map, el.get('href')))

    for err in parser.error_log:
        print("HTML WARN: {0}".format(err))
    text = etree.tostring(html, encoding=str, method="html")

    f = open(fn, "w")
    f.write(text)
    f.close()

def preprocess_css_file(fn):
    f = open(fn, "r")
    text = f.read()
    f.close()

    # note that query string is not used in css files

    text = text.replace('../DejaVuSansMonoCondensed60.ttf', 'DejaVuSansMonoCondensed60.ttf')
    text = text.replace('../DejaVuSansMonoCondensed75.ttf', 'DejaVuSansMonoCondensed75.ttf')

    # QT Help viewer doesn't understand nth-child
    text = text.replace('nth-child(1)', 'first-child')

    f = open(fn, "w")
    f.write(text)
    f.close()

def main():
    parser = argparse.ArgumentParser(prog='preprocess.py')
    parser.add_argument('--src', type=str, help='Source directory where raw website copy resides')
    parser.add_argument('--dst', type=str, help='Destination folder to put preprocessed archive to')
    args = parser.parse_args()

    root = args.dst
    src = args.src

    # copy the source tree
    rmtree_if_exists(root)
    shutil.copytree(src, root)

    rearrange_archive(root)

    rename_map = find_files_to_be_renamed(root)
    rename_files(rename_map)

    # clean the html files
    for fn in find_html_files(root):
        preprocess_html_file(root, fn, rename_map)

    # append css modifications

    f = open("preprocess-css.css", "r")
    css_app = f.read()
    f.close()
    f = open(os.path.join(root, 'common/site_modules.css'), "a")
    f.write(css_app)
    f.close()

    # clean the css files

    for fn in [ os.path.join(root, 'common/site_modules.css'),
                os.path.join(root, 'common/ext.css') ]:
        preprocess_css_file(fn)


if __name__ == "__main__":
    main()
