"""
Hook for doing any preprocessing to the burnin nuke script.
"""
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

class PreprocessNuke(HookBaseClass):

    def get_processed_script(self, nuke_script_path, **kwargs):
        """
        Preprocess the burnin nuke script and return the processed script path

        :param nuke_script_path: Path of the original nuke script to operate on
        :param kwargs: Any additional items required to do the preprocessing
        :return: Processed nuke script path
        """
        # default implementation returns the nuke script as is
        # intended to be overridden as required
        return nuke_script_path
