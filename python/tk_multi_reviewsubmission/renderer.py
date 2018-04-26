# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import sgtk
import os
import copy
from datetime import datetime
import hashlib
import pickle
import re
import sys
import subprocess
import time
from sgtk.platform.qt import QtCore


try:
    import nuke
except ImportError:
    nuke = None


class Renderer(object):
    def __init__(self):
        """
        Construction
        """
        self.__app = sgtk.platform.current_bundle()
        self._font = os.path.join(self.__app.disk_location, "resources", "liberationsans_regular.ttf")
        self._context_fields = self.__app.context.as_template_fields()

        self._burnin_nk = ''
        burnin_template = self.__app.get_template("burnin_path")
        if burnin_template:
            self._burnin_nk = burnin_template.apply_fields(self._context_fields)
        # If a show specific burnin file has not been defined, take it from the default location
        if not os.path.isfile(self._burnin_nk):
            self._burnin_nk = os.path.join(self.__app.disk_location, "resources", "burnin.nk")

        self._logo = None
        logo_template = self.__app.get_template("slate_logo")
        logo_file_path = logo_template.apply_fields(self._context_fields)
        if os.path.isfile(logo_file_path):
            self._logo = logo_file_path
        else:
            self._logo = ""

        # now transform paths to be forward slashes, otherwise it wont work on windows.
        if sys.platform == "win32":
            self._font = self._font.replace(os.sep, "/")
            self._logo = self._logo.replace(os.sep, "/")
            self._burnin_nk = self._burnin_nk.replace(os.sep, "/")

    def gather_nuke_render_info(self, path, output_path,
                                width, height,
                                first_frame, last_frame,
                                version, name,
                                color_space, burnin_nk):
        # First get Nuke executable path from project configuration environment
        setting_key_by_os = {'win32': 'nuke_windows_path',
                             'linux2': 'nuke_linux_path',
                             'darwin': 'nuke_mac_path'}
        nuke_exe_path = self.__app.get_setting(setting_key_by_os[sys.platform])

        # get the Write node settings we'll use for generating the Quicktime
        writenode_quicktime_settings = self.__app.execute_hook_method("codec_settings_hook",
                                                                      "get_quicktime_settings")

        # making the python script passed to nuke configurable as a setting because
        # making it a hook would still not allow us to subprocess it out
        render_script_path = ''
        render_script_template = self.__app.get_template("render_script")
        if render_script_template:
            render_script_path = render_script_template.apply_fields(self._context_fields)

        # If a show specific render script has not been defined, take it from the default location
        if not os.path.isfile(render_script_path):
            render_script_path = os.path.join(self.__app.disk_location, "hooks",
                                              "nuke_batch_render_movie.py")

        serialized_context = self.__app.context.serialize()

        app_settings = {
            'version_number_padding': self.__app.get_setting('version_number_padding'),
            'slate_logo': self._logo,
        }

        render_info = {
            'burnin_nk': burnin_nk,
            'slate_font': self._font,
            'codec_settings': {'quicktime': writenode_quicktime_settings},
        }

        # set needed paths and force them to use forward slashes for use in Nuke (for Windows)
        src_frames_path = path.replace('\\', '/')
        movie_output_path = output_path.replace('\\', '/')

        nuke_render_info = {
            'width': width,
            'height': height,
            'first_frame': first_frame,
            'last_frame': last_frame,
            'version': version,
            'name': name,
            'color_space': color_space,
            'nuke_exe_path': nuke_exe_path,
            'render_script_path': render_script_path,
            'serialized_context': serialized_context,
            'app_settings': app_settings,
            'render_info': render_info,
            'src_frames_path': src_frames_path,
            'movie_output_path': movie_output_path,
        }
        return nuke_render_info

    @staticmethod
    def remove_html(string):
        return re.sub('<.+?>', '', string)

    def replaceVars(self, attr, data):
        """
        Replace the variables in a nuke script
        Variables defined by [* *] or \[* *]
        """
        # get rid of nukes escape characters (fancy, huh)
        attr = attr.replace("\[*", "[*")

        # look for anything with a [* *] pattern
        vars = re.compile("\[\*[A-Za-z_ %/:0-9()\-,.\+]+\*\]").findall(attr)

        dt = datetime.now()

        for var in vars:
            var_tmp = var.replace("[*", "").replace("*]", "")
            # Replace the date/time variables
            if var_tmp.startswith('date '):
                date_str = var_tmp.replace('date ', '')
                attr = attr.replace(var, dt.strftime(date_str))

            # Replace the frame number variables
            elif (var_tmp.lower() == "numframes" and
                          data.get('first_frame') != None and data.get('first_frame') != '' and
                          data.get('last_frame') != None and data.get('last_frame') != ''):
                range = str(int(data.get('lf')) - int(data.get('first_frame')))
                attr = attr.replace(var, range)

            # and the increment that may be at the end of the frame number
            elif "+" in var_tmp.lower():
                (tmp, num) = var_tmp.split("+")
                sum = str(int(data.get(tmp)) + int(num))
                attr = attr.replace(var, sum)

            # make it easier to enter screen coordinates
            # that vary with resolution, by normalizing to
            # (-0.5 -0.5) to (0.5 0.5)
            elif "screenspace" in var_tmp.lower():
                var_tmp = var_tmp.replace("(", " ").replace(",", " ").replace(")", " ")
                (key, xString, yString) = var_tmp.split()
                xFloat = float(xString) + 0.5
                yFloat = float(yString) + 0.5
                translateString = (
                "{{SHUFFLE_CONSTANT.actual_format.width*(%s) i} {SHUFFLE_CONSTANT.actual_format.height*(%s) i}}" % (
                str(xFloat), str(yFloat)))
                attr = attr.replace(var, translateString)

            # TODO: do we handle this differently?
            # Replace the showname
            # (now resolved in resolveMainProcessVariables)
            elif var_tmp == "showname":
                attr = attr.replace(var, str(data.get('showname')))

            # remove knobs that have a [**] value but nothing in data
            elif (data.get(var_tmp) == '' or
                          data.get(var_tmp) == None or
                          data.get(var_tmp) == "None"):
                regexp = ".*\[\*"
                regexp += var_tmp
                regexp += "\*\].*"
                line = re.compile(regexp).findall(attr)
                if line != None and len(line) > 0:
                    if line[0].count('message') > 0:
                        attr = attr.replace(var, str('""'))
                    else:
                        attr = attr.replace(var, "None")

            else:
                replaceval = self.remove_html(str(data.get(var_tmp)))
                if (replaceval == ""):
                    replaceval == '""'
                attr = attr.replace(var, str(replaceval))
        return attr
    # end replaceVars

    def render_movie_in_nuke(self, path, output_path,
                             width, height,
                             first_frame, last_frame,
                             version, name,
                             color_space,
                             replace_data,
                             active_progress_info=None):
        # replace tokens in self._burnin_nk and save it in /var/tmp
        tmp_file_prefix = "reviewsubmission_tmp_nuke_script"
        tmp_file_name = "%s_%s.nk" % (tmp_file_prefix, hashlib.md5(str(time.time())).hexdigest())
        tmp_full_path = os.path.join("/var", "tmp", tmp_file_name)

        self.__app.log_debug("Saving nuke script to: {}".format(tmp_full_path))
        with open(self._burnin_nk, 'r') as source_script_file, open(tmp_full_path, 'w') as tmp_script_file:
            nuke_script_text = source_script_file.read()
            nuke_script_text = self.replaceVars(nuke_script_text, replace_data)
            tmp_script_file.write(nuke_script_text)

        render_info = self.gather_nuke_render_info(path, output_path, width, height, first_frame,
                                                   last_frame, version, name, color_space, tmp_full_path)
        run_in_batch_mode = True if nuke is None else False

        event_loop = QtCore.QEventLoop()
        thread = ShooterThread(render_info, run_in_batch_mode)
        thread.finished.connect(event_loop.quit)
        thread.start()
        event_loop.exec_()

        # log any errors generated in the thread
        thread_error_msg = thread.get_errors()
        if thread_error_msg:
            self.__app.log_error("ERROR:\n" + thread_error_msg)
            # Do not clutter user message with any warnings etc from Nuke. Print only traceback.
            # TODO: is there a better way?
            try:
                subproc_traceback = 'Traceback' + thread_error_msg.split('Traceback')[1]
            except IndexError:
                subproc_traceback = thread_error_msg
            # Make sure we don't display a success message. TODO: Custom exception?
            raise Exception("Error in tk-multi-reviewsubmission: " + subproc_traceback)

class ShooterThread(QtCore.QThread):
    def __init__(self, render_info, batch_mode=True, active_progress_info=None):
        QtCore.QThread.__init__(self)
        self.render_info = render_info
        self.batch_mode = batch_mode
        self.active_progress_info = active_progress_info
        self.subproc_error_msg = ''

    def get_errors(self):
        return self.subproc_error_msg

    def run(self):
        if self.batch_mode:
            nuke_flag = '-t'
        else:
            nuke_flag = '-it'

        cmd_and_args = [
            self.render_info['nuke_exe_path'], nuke_flag, self.render_info['render_script_path'],
            '--path', pickle.dumps(self.render_info['src_frames_path']),
            '--output_path', pickle.dumps(self.render_info['movie_output_path']),
            '--width', pickle.dumps(self.render_info['width']),
            '--height', pickle.dumps(self.render_info['height']),
            '--version', pickle.dumps(self.render_info['version']),
            '--name', pickle.dumps(self.render_info['name']),
            '--color_space', pickle.dumps(self.render_info['color_space']),
            '--first_frame', pickle.dumps(self.render_info['first_frame']),
            '--last_frame', pickle.dumps(self.render_info['last_frame']),
            '--app_settings', pickle.dumps(self.render_info['app_settings']),
            '--shotgun_context', self.render_info['serialized_context'],
            '--render_info', pickle.dumps(self.render_info['render_info']),
        ]

        env = copy.deepcopy(os.environ)
        env["TANK_CONTEXT"] = self.render_info['serialized_context']
        p = subprocess.Popen(cmd_and_args, stderr=subprocess.PIPE, env=env, bufsize=1)

        error_lines = []

        while p.poll() is None:
            stderr_line = p.stderr.readline()
            if stderr_line != '':
                error_lines.append(stderr_line.rstrip())

        if p.returncode != 0:
            self.subproc_error_msg = '\n'.join(error_lines)
