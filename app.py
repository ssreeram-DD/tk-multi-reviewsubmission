# Copyright (c) 2013 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Sgtk Application for handling Quicktime generation and review submission
"""

import sgtk
import sgtk.templatekey
import copy
import os

class MultiReviewSubmissionApp(sgtk.platform.Application):
    """
    Main Application class
    """

    def init_app(self):
        """
        App initialization
        
        Note, this app doesn't register any commands at the moment as all it's functionality is
        provided through it's API.
        """
        pass

    @property
    def context_change_allowed(self):
        """
        Specifies that context changes are allowed.
        """
        return True

    def get_resolved_write_nodes(self, fields):
        """
        Returns the resolved paths of the write nodes that the app should run/use from the nuke file.
        """

        resolved_mapping = {}
        extra_write_nodes_path_info = self.get_setting("extra_write_nodes_path_info")

        if extra_write_nodes_path_info:
            for write_node_name, write_node_template_name in extra_write_nodes_path_info.iteritems():
                # resolve the path from the template
                write_node_template = self.get_template_by_name(write_node_template_name)
                write_node_path = write_node_template.apply_fields(fields)

                resolved_mapping[write_node_name] = write_node_path

        return resolved_mapping

    def render_and_submit(self, template, fields, first_frame, last_frame, sg_publishes, sg_task,
                          comment, thumbnail_path, progress_cb):
        """
        *** Deprecated ***
        Please use 'render_and_submit_version' instead
        """
        self.log_warning("The method 'render_and_submit()' has been deprecated as it didn't allow the colorspace "
                         "of the input frames to be specified.  Please use 'render_and_submit_version()' "
                         "instead.")
        
        # call new version
        return self.render_and_submit_version(template, fields, first_frame, last_frame, sg_publishes, sg_task,
                                  comment, thumbnail_path, progress_cb)

    def render_and_return_paths(self, path, fields, first_frame, last_frame, sg_publishes, sg_task,
                                comment, thumbnail_path, progress_cb, color_space=None, *args, **kwargs):
        """
        Render and return the paths that are processed by the nuke hook.

        :param path:            The path where frames should be found.
        :param fields:          Dictionary of fields to be used to fill out the template with.
        :param first_frame:     The first frame of the sequence of frames.
        :param last_frame:      The last frame of the sequence of frames.
        :param sg_publishes:    A list of shotgun published file objects to link the publish against.
        :param sg_task:         A Shotgun task object to link against. Can be None.
        :param comment:         A description to add to the Version in Shotgun.
        :param thumbnail_path:  The path to a thumbnail to use for the version when the movie isn't
                                being uploaded to Shotgun (this is set in the config)
        :param progress_cb:     A callback to report progress with.
        :param color_space:     The colorspace of the rendered frames

        :returns:               List of processed paths that have been rendered by the nuke hook.
        """

        tk_multi_reviewsubmission = self.import_module("tk_multi_reviewsubmission")

        progress_cb(10, "Preparing...")

        extra_write_node_mapping = self.get_resolved_write_nodes(fields)

        # Make sure we don't overwrite the caller's fields
        fields = copy.copy(fields)

        # Movie output width and height
        width = self.get_setting("movie_width")
        height = self.get_setting("movie_height")
        fields["width"] = width
        fields["height"] = height

        # Get an output path for the movie.
        output_path_template = self.get_template("movie_path_template")
        output_path = output_path_template.apply_fields(fields)

        fields["description"] = comment

        # Render and Submit
        renderer = tk_multi_reviewsubmission.Renderer()
        processed_paths = renderer.render_movie_in_nuke(path, output_path, extra_write_node_mapping, width, height,
                                                        first_frame, last_frame, fields.get("version", 0),
                                                        fields.get("name", "Unnamed"), color_space, fields, progress_cb)

        return processed_paths

    def submit_version(self, path, path_to_upload, fields, first_frame, last_frame, sg_publishes, sg_task,
                       comment, thumbnail_path, progress_cb, color_space=None, *args, **kwargs):
        """
        Create a version entity for the given path.

        :param path:            The path where frames should be found.
        :param path_to_upload:  The path to create the version entity for.
        :param fields:          Dictionary of fields to be used to fill out the template with.
        :param first_frame:     The first frame of the sequence of frames.
        :param last_frame:      The last frame of the sequence of frames.
        :param sg_publishes:    A list of shotgun published file objects to link the publish against.
        :param sg_task:         A Shotgun task object to link against. Can be None.
        :param comment:         A description to add to the Version in Shotgun.
        :param thumbnail_path:  The path to a thumbnail to use for the version when the movie isn't
                                being uploaded to Shotgun (this is set in the config)
        :param progress_cb:     A callback to report progress with.
        :param color_space:     The colorspace of the rendered frames

        :returns:               The Version Shotgun entity dictionary that was created.
        """

        tk_multi_reviewsubmission = self.import_module("tk_multi_reviewsubmission")

        # Is the app configured to do anything?
        upload_to_shotgun = self.get_setting("upload_to_shotgun")
        store_on_disk = self.get_setting("store_on_disk")
        if not upload_to_shotgun and not store_on_disk:
            self.log_warning("App is not configured to store images on disk nor upload to shotgun!")
            return None

        # Make sure we don't overwrite the caller's fields
        fields = copy.copy(fields)

        # Get the name for the Version entity
        version_template = self.get_template("sg_version_name_template")
        version_name = None
        if version_template:
            version_name = version_template.apply_fields(fields)

        # Submit Version
        progress_cb(50, "Creating Shotgun Version and uploading movie")
        submitter = tk_multi_reviewsubmission.Submitter()
        sg_version = submitter.submit_version(path,
                                              path_to_upload,
                                              thumbnail_path,
                                              sg_publishes,
                                              sg_task,
                                              comment,
                                              store_on_disk,
                                              first_frame,
                                              last_frame,
                                              upload_to_shotgun,
                                              version_name)

        # Remove from filesystem if required
        if not store_on_disk and os.path.exists(path_to_upload):
            progress_cb(90, "Deleting rendered movie")
            os.unlink(path_to_upload)

        # log metrics for this app's usage
        try:
            self.log_metric("Render & Submit Version", log_version=True)
        except:
            # ignore any errors. ex: metrics logging not supported
            pass

        return sg_version

    def render_and_submit_version(self, path, fields, first_frame, last_frame, sg_publishes, sg_task,
                                  comment, thumbnail_path, progress_cb, color_space=None, *args, **kwargs):
        """
        Main application entry point to be called by other applications / hooks.

        :param path:            The path where frames should be found.
        :param fields:          Dictionary of fields to be used to fill out the template with.
        :param first_frame:     The first frame of the sequence of frames.
        :param last_frame:      The last frame of the sequence of frames.
        :param sg_publishes:    A list of shotgun published file objects to link the publish against.
        :param sg_task:         A Shotgun task object to link against. Can be None.
        :param comment:         A description to add to the Version in Shotgun.
        :param thumbnail_path:  The path to a thumbnail to use for the version when the movie isn't
                                being uploaded to Shotgun (this is set in the config)
        :param progress_cb:     A callback to report progress with.
        :param color_space:     The colorspace of the rendered frames

        :returns:               The Version Shotgun entity dictionary that was created.
        """
        tk_multi_reviewsubmission = self.import_module("tk_multi_reviewsubmission")
        
        # Is the app configured to do anything?
        upload_to_shotgun = self.get_setting("upload_to_shotgun")
        store_on_disk = self.get_setting("store_on_disk")
        if not upload_to_shotgun and not store_on_disk:
            self.log_warning("App is not configured to store images on disk nor upload to shotgun!")
            return None

        # Make sure we don't overwrite the caller's fields
        fields = copy.copy(fields)

        # Get the name for the Version entity
        version_template = self.get_template("sg_version_name_template")
        version_name = None
        if version_template:
            version_name = version_template.apply_fields(fields)

        # get processed path
        progress_cb(20, "Rendering Movie...")
        processed_paths = self.render_and_return_paths(path, fields, first_frame, last_frame, sg_publishes, sg_task,
                                                       comment, thumbnail_path, progress_cb, color_space, *args, **kwargs)

        assert len(processed_paths) == 1, "Can't create versions for more than one files!"
        output_path = processed_paths[0]

        # Submit Version
        progress_cb(50, "Creating Shotgun Version and uploading movie")
        submitter = tk_multi_reviewsubmission.Submitter()
        sg_version = submitter.submit_version(path, 
                                              output_path,
                                              thumbnail_path,
                                              sg_publishes, 
                                              sg_task, 
                                              comment, 
                                              store_on_disk,
                                              first_frame,
                                              last_frame,
                                              upload_to_shotgun,
                                              version_name)
            
        # Remove from filesystem if required
        if not store_on_disk and os.path.exists(output_path):
            progress_cb(90, "Deleting rendered movie")
            os.unlink(output_path)

        # log metrics for this app's usage
        try:
            self.log_metric("Render & Submit Version", log_version=True)
        except:
            # ignore any errors. ex: metrics logging not supported
            pass

        return sg_version
