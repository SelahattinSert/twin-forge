"""Domain exceptions presented by the TwinForge CLI."""


class TwinForgeError(Exception):
    """Base class for expected, actionable TwinForge failures."""


class InvalidVideoError(TwinForgeError):
    """The input file is absent or contains no usable video stream."""


class VideoDecodeError(TwinForgeError):
    """The video could not be inspected or decoded."""


class NoUsableFramesError(TwinForgeError):
    """No candidate frame passed basic image quality checks."""


class BackendUnavailableError(TwinForgeError):
    """The requested inference backend is not installed or available."""


class ModelLoadError(TwinForgeError):
    """A reconstruction model could not be initialized."""


class OutOfMemoryReconstructionError(TwinForgeError):
    """The accelerator ran out of memory during reconstruction."""


class ReconstructionFailedError(TwinForgeError):
    """The backend failed to produce a valid reconstruction."""


class ExportError(TwinForgeError):
    """A reconstruction artifact could not be written."""
