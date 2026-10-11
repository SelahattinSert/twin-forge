"""Typed selection failures with fixed public recovery guidance."""

MESSAGES = {
    "pixel_provenance_unavailable": "Source-to-model pixel provenance is unavailable. Choose points in 3D or open a scene with verified image support.",
    "pixel_outside_crop": "Source pixel is outside the model crop. Choose points inside the supported area of the photo.",
    "pixel_not_retained": "Model pixel has no unique retained PLY row. Choose another supported pixel or a different source photo.",
    "masked_endpoints": "Invalid or masked endpoints cannot be measured. Choose valid supported points or a different source photo.",
    "stale_correction": "Observation revision changed. Reopen the observation before correcting it, then review the latest saved selection.",
}


class MeasurementValidationError(ValueError):
    """Only an allowlisted code can produce a public action error."""

    status = 422

    def __init__(self, code: str):
        self.code = code
        self.message = MESSAGES[code]
        super().__init__(self.message)
