SUPPORTED_PSM_MODES = [3, 4, 6]

PSM_TO_PROVIDER = {
    3: "tesseract-psm3",
    4: "tesseract-psm4",
    6: "tesseract-psm6",
}

PROVIDER_TO_PSM = {v: k for k, v in PSM_TO_PROVIDER.items()}
