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

    def gather_nuke_render_info(self, path_to_frames, path_to_movie, extra_write_node_mapping, width, height,
                                first_frame, last_frame, version, name, color_space, burnin_nk):
        """
        Prepares the render settings for the nuke subprocess hook

        :param path_to_frames:  The path where frames should be found.
        :param path_to_movie:   The path where the movie should be written to
        :param extra_write_node_mapping: Mapping of write nodes with their output paths that should be rendered,
        other than the movie write node
        :param width:       Movie width
        :param height:      Movie height
        :param first_frame: The first frame of the sequence of frames
        :param last_frame:  The last frame of the sequence of frames
        :param version:     Version currently being published
        :param name:        Name of the file being published
        :param color_space: Colorspace used to create the frames
        :param burnin_nk:   Path to the nuke file to be used for processing

        :return:            Dictionary of settings to be used by the subprocess.
        """
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
        src_frames_path = path_to_frames.replace('\\', '/')
        movie_output_path = path_to_movie.replace('\\', '/')

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
            'extra_write_node_mapping': extra_write_node_mapping,
        }
        return nuke_render_info

    def render_in_nuke(self, path_to_frames, path_to_movie, extra_write_node_mapping, width, height, first_frame,
                       last_frame, version, name, color_space, fields=None, active_progress_info=None):
        """
        Renders the movie using a Nuke subprocess,
        along with slate/burnins using all the app settings.

        :param path_to_frames:  The path where frames should be found.
        :param path_to_movie:   The path where the movie should be written to
        :param extra_write_node_mapping: Mapping of write nodes with their output paths that should be rendered,
        other than the movie write node
        :param width:           Movie width
        :param height:          Movie height
        :param first_frame:     The first frame of the sequence of frames
        :param last_frame:      The last frame of the sequence of frames
        :param version:         Version currently being published
        :param name:            Name of the file being published
        :param color_space:     Colorspace used to create the frames
        :param fields:          Any additional information to be used in slate/burnins
        :param active_progress_info: Any function that receives the progress percentage
                                     Can be used to update GUI
        """
        # add to information passed for preprocessing
        fields["first_frame"] = first_frame
        fields["last_frame"] = last_frame
        fields["path"] = path_to_frames

        # preprocess self._burnin_nk to replace tokens
        processed_nuke_script_path = self.__app.execute_hook_method("preprocess_nuke_hook",
                                                                    "get_processed_script",
                                                                    nuke_script_path=self._burnin_nk,
                                                                    fields=fields)

        render_info = self.gather_nuke_render_info(path_to_frames, path_to_movie, extra_write_node_mapping, width,
                                                   height, first_frame, last_frame, version, name, color_space,
                                                   processed_nuke_script_path)
        run_in_batch_mode = True if nuke is None else False

        event_loop = QtCore.QEventLoop()
        thread = ShooterThread(render_info, run_in_batch_mode, active_progress_info)
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

        processed_paths = thread.get_processed_paths()
        if not processed_paths:
            raise Exception("Error in tk-multi-reviewsubmission: No output paths were found after the render!")

        else:
            # in the render hook we expect the thread to return us ':' separated paths
            # return a list of paths
            processed_paths_list = processed_paths.split(":")
            for path_to_frames in processed_paths_list:
                active_progress_info(msg="Created %s" % path_to_frames, stage={"item": {"name": "Render"},
                                                                     "output": {"name": "Nuke"}})
            return processed_paths_list


class ShooterThread(QtCore.QThread):
    def __init__(self, render_info, batch_mode=True, active_progress_info=None):
        QtCore.QThread.__init__(self)
        self.render_info = render_info
        self.batch_mode = batch_mode
        self.active_progress_info = active_progress_info
        self.subproc_error_msg = ''
        self.processed_paths = ''

    def get_errors(self):
        return self.subproc_error_msg

    def get_processed_paths(self):
        return self.processed_paths

    def run(self):
        if self.batch_mode:
            nuke_flag = '-t'
        else:
            nuke_flag = '-it'

        cmd_and_args = [
            self.render_info['nuke_exe_path'], nuke_flag, self.render_info['render_script_path'],
            '--path_to_frames', pickle.dumps(self.render_info['src_frames_path']),
            '--path_to_movie', pickle.dumps(self.render_info['movie_output_path']),
            '--extra_write_node_mapping', pickle.dumps(self.render_info['extra_write_node_mapping']),
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

        output_lines = []

        while p.poll() is None:
            line = p.stderr.readline()
            if line != '':
                output_lines.append(line.rstrip())

            # disable the active progress update, clutters the whole UI
            # if line.startswith('Writing ') and self.active_progress_info:
            #     # matching the _process_cb method of create_version.py
            #     self.active_progress_info(msg=line.rstrip(), stage={"item": {"name": "Render"},
            #                                                         "output": {"name": "Nuke"}})

        if p.returncode != 0:
            output_str = '\n'.join(output_lines)
            self.subproc_error_msg = output_str.split('[RETURN_STATUS_DATA]')[1]
            del output_str
        else:
            # we should get the paths now!!
            output_str = '\n'.join(output_lines)
            self.processed_paths = output_str.split('[PROCESSED_PATHS]')[1]
            del output_str
