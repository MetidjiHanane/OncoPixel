# Models: architectures, checkpoint verification and local test

This page says exactly what the application expects from your two checkpoints, how to check them, and how to test both models on your MacBook Pro M1.

The checkpoints are **never** uploaded and **never** committed. `.gitignore` excludes `models/**/*.pt`, `*.pth`, `*.onnx` and `*.ckpt`.

## 1. Where the files go

| Model | Default path | Override |
|---|---|---|
| Classification | `models/classification/best.pt` | Models page, or env `ONCOPIXEL_CLASSIFIER_CKPT` |
| Segmentation | `models/segmentation/tumor_seg_model.pt` | Models page, or env `ONCOPIXEL_SEGMENTER_CKPT` |

Order of precedence: environment variable, then the path saved in Settings (Models page), then the default folder. `ONCOPIXEL_MODELS_DIR` moves the whole default folder. In the packaged app the default folder is `~/Library/Application Support/OncoPixel/models`.

## 2. What was taken from your notebooks

Nothing is invented. The loaders were written from `brisc_classification.ipynb` and your `segmenter.py` (used unchanged as `backend/oncopixel/ml/segmenter.py`).

### Classification

| Item | Value |
|---|---|
| Architecture | timm model named in the checkpoint (`model` key), ConvNeXt-Tiny in your notebook, created with `pretrained=False` and `num_classes=4` |
| Checkpoint keys | `state`, `classes`, `model`, `size` (required); `class_to_idx`, `temperature`, `epoch`, `merge_val_into_train` (optional) |
| Class order | `glioma, meningioma, no_tumor, pituitary`. The loader refuses a checkpoint whose saved `classes` differ. No re-mapping is guessed. |
| Input | grayscale replicated to 3 channels, resized to `size x size` (256), ImageNet mean/std normalisation |
| Output | softmax of `(logits + logits_hflip) / 2 / temperature` (flip averaging can be switched off in Settings) |
| Loading | `torch.load(..., weights_only=True)`, then `load_state_dict(strict=True)` |
| Score shown | "model confidence estimate": the maximum softmax value after temperature scaling. Not a calibrated clinical probability. Below 0.90 (configurable) the study is flagged for review. |
| Grad-CAM | last stage of the network (`stages[-1]`) |

### Segmentation

| Item | Value |
|---|---|
| Architecture | U-Net with ResNet-34 encoder (`segmentation_models_pytorch`), rebuilt by your `TumorSegmenter` from the saved `config` |
| Checkpoint keys | `config`, `state_dict` |
| Input | 8-bit grayscale, letterboxed to 512 x 512 (aspect preserved), scaled to [0, 1] |
| Output | probability map cropped and resized back to the original size; threshold, clean-up and contour are network-free (`rethreshold`) |
| Threshold | the value validated with the model (from the checkpoint config) unless you set one in Settings |

## 3. What happens when something is wrong

| Situation | Behaviour |
|---|---|
| File missing | Red/amber banner on every page; Models page shows the searched path; analysis endpoints answer HTTP 409 `MODEL_MISSING`; nothing is stored. |
| File present but wrong | Models page shows the reason code: `unreadable_checkpoint`, `missing_keys`, `class_order_mismatch`, `weights_do_not_match_architecture`. No analysis is run. |
| Only one model available | The available stage can be run on its own and is labelled; the other stage is reported as unavailable. |
| Random-weight test file | Detected by a `fixture: true` marker and flagged with a red banner. Test files carry no meaning. |

## 4. Verify the checkpoints (command line)

From the project folder, after `./scripts/setup-mac.sh`:

```bash
./scripts/verify-models.sh                                   # default folder
./scripts/verify-models.sh --image ~/Desktop/slice.png       # also run both models on a real slice
./scripts/verify-models.sh --device cpu                      # force CPU
./scripts/verify-models.sh --out verify-report.json          # save the full report
```

It prints PASS or FAIL for each check and exits with code 0 only if both models pass:

- Classifier: file loads with `weights_only=True`; keys present; classes equal `glioma, meningioma, no_tumor, pituitary`; the timm model builds; `load_state_dict(strict=True)` succeeds; forward pass gives 4 finite scores that sum to 1; Grad-CAM has the image size.
- Segmenter: file loads; `config` and `state_dict` present; the U-Net builds; weights load; the probability map has the image size and values in [0, 1].
- Per model: SHA-256 of the file, input size, device, and forward time.

Read the output carefully:

- A line `untrained test model` means the file is a random-weight fixture, not your trained model.
- A **PASS only proves the file fits the architecture and runs.** It does not prove the model is accurate. To check accuracy, run your notebooks' evaluation, or compare a few known cases by eye (below).

## 5. Test both models on the MacBook Pro M1

1. `./scripts/setup-mac.sh`. Python 3.10 to 3.13 (arm64) and Node 18 or newer are needed. The standard PyTorch wheel for Apple Silicon includes MPS.
2. Place the two checkpoints in `models/` as above.
3. `./scripts/verify-models.sh --image <a T1 slice you know the answer for>`. Note the device line (`mps` or `cpu`) and forward times. The target is under 10 seconds per image on your 8 GB machine.
4. `./scripts/run.sh`. Create the account. Open **Models**: both cards should say **Ready**, with the SHA-256 and input sizes shown. Press **Run self-test**: all checks should pass.
5. **New analysis**, import 4 images you know (one per class, including one without tumor). Press **Analyze**. For each:
   - the predicted class and confidence match what your notebook gives for the same image (the same preprocessing and flip averaging are used);
   - the mask and contour sit on the tumor; try the threshold slider;
   - Measurements show pixels (PNG/JPG) or millimetres (DICOM, or after entering spacing).
6. If MPS gives an error or odd numbers, set **Settings, Compute device, CPU** and compare. Both should agree to within small floating-point differences. If they do not, please report the operator in the error message.
7. If you see `class_order_mismatch`, the saved `classes` list in the checkpoint is not in the order above. Do not edit the application: re-save the checkpoint from the notebook with `classes` in the notebook order.

### Comparing with your notebook

For one image, print in the notebook the class probabilities with the same settings (flip averaging on, temperature from the checkpoint). The application's "Score for each class" for that image should match to about three decimals on CPU. The JSON export of a study (`/studies/{id}/export/json`) contains the raw per-class scores and the checkpoint ID for the record.

### Memory on 8 GB

Both models are loaded lazily and only one inference runs at a time. If memory is tight, close other applications, use CPU, and keep Grad-CAM and the uncertainty map for the images you care about (the uncertainty map runs six extra forward passes).

## 6. Test fixtures (developers only)

`python backend/scripts/make_test_fixtures.py` writes random-weight checkpoints and a phantom image to `backend/tests/_fixtures` (ignored by Git). The pytest suite uses them. They exist only to test the software and are always flagged as untrained.
