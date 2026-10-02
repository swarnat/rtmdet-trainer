"""Build the complete MMDetection training config for one training run."""
from __future__ import annotations

import math
from dataclasses import dataclass

from odcore.classes import CLASS_NAMES

from .base_config import load_base_config


@dataclass(frozen=True)
class TrainParams:
    data_root: str          # local snapshot dir with annotations/{train,val}.json and images/
    work_dir: str
    load_from: str          # checkpoint used to initialise all weights
    input_width: int
    input_height: int
    epochs: int
    batch_size: int
    learning_rate: float | None
    num_workers: int
    num_train_images: int
    use_amp: bool
    seed: int


def default_learning_rate(batch_size: int) -> float:
    """Fine-tuning LR for AdamW (RTMDet's 0.004 is for batch 256 from scratch)."""
    return 0.00025 * batch_size / 4


def stage2_epochs(epochs: int) -> int:
    """Last epochs without Mosaic/MixUp (RTMDet uses 20 of 300)."""
    return 0 if epochs < 5 else max(1, round(epochs * 0.15))


def build_config(p: TrainParams):
    cfg = load_base_config(num_classes=len(CLASS_NAMES))
    w, h = p.input_width, p.input_height
    pad = dict(img=(114, 114, 114))
    metainfo = dict(classes=CLASS_NAMES, palette=[(220, 20, 60), (0, 160, 255), (255, 170, 0)])

    # Negative images/crops (no boxes) must stay in the pipeline:
    # allow_negative_crop=True and keep_empty=False (True would drop empty samples).
    train_pipeline = [
        dict(type="LoadImageFromFile", backend_args=None),
        dict(type="LoadAnnotations", with_bbox=True),
        dict(type="CachedMosaic", img_scale=(w, h), pad_val=114.0, max_cached_images=20, random_pop=False),
        dict(type="RandomResize", scale=(w * 2, h * 2), ratio_range=(0.5, 1.5), keep_ratio=True),
        dict(type="RandomCrop", crop_size=(w, h), allow_negative_crop=True),
        dict(type="YOLOXHSVRandomAug"),
        dict(type="RandomFlip", prob=0.5),
        dict(type="Pad", size=(w, h), pad_val=pad),
        dict(type="CachedMixUp", img_scale=(w, h), ratio_range=(1.0, 1.0), max_cached_images=10,
             random_pop=False, pad_val=(114, 114, 114), prob=0.5),
        dict(type="FilterAnnotations", min_gt_bbox_wh=(1, 1), keep_empty=False),
        dict(type="PackDetInputs"),
    ]
    train_pipeline_stage2 = [
        dict(type="LoadImageFromFile", backend_args=None),
        dict(type="LoadAnnotations", with_bbox=True),
        dict(type="RandomResize", scale=(w, h), ratio_range=(0.5, 2.0), keep_ratio=True),
        dict(type="RandomCrop", crop_size=(w, h), allow_negative_crop=True),
        dict(type="YOLOXHSVRandomAug"),
        dict(type="RandomFlip", prob=0.5),
        dict(type="Pad", size=(w, h), pad_val=pad),
        dict(type="FilterAnnotations", min_gt_bbox_wh=(1, 1), keep_empty=False),
        dict(type="PackDetInputs"),
    ]
    test_pipeline = [
        dict(type="LoadImageFromFile", backend_args=None),
        dict(type="Resize", scale=(w, h), keep_ratio=True),
        dict(type="Pad", size=(w, h), pad_val=pad),
        dict(type="LoadAnnotations", with_bbox=True),
        dict(type="PackDetInputs", meta_keys=("img_id", "img_path", "ori_shape", "img_shape", "scale_factor")),
    ]

    persistent = p.num_workers > 0
    cfg.train_dataloader = dict(
        batch_size=p.batch_size,
        num_workers=p.num_workers,
        persistent_workers=persistent,
        pin_memory=True,
        sampler=dict(type="DefaultSampler", shuffle=True),
        batch_sampler=None,
        dataset=dict(
            type="CocoDataset",
            data_root=p.data_root,
            metainfo=metainfo,
            ann_file="annotations/train.json",
            data_prefix=dict(img="images/"),
            # Negative images (no boxes) are valid training samples and must be kept
            filter_cfg=dict(filter_empty_gt=False, min_size=1),
            pipeline=train_pipeline,
            backend_args=None,
        ),
    )
    val_batch = min(p.batch_size, 8)
    cfg.val_dataloader = dict(
        batch_size=val_batch,
        num_workers=min(p.num_workers, 2),
        persistent_workers=min(p.num_workers, 2) > 0,
        drop_last=False,
        sampler=dict(type="DefaultSampler", shuffle=False),
        dataset=dict(
            type="CocoDataset",
            data_root=p.data_root,
            metainfo=metainfo,
            ann_file="annotations/val.json",
            data_prefix=dict(img="images/"),
            test_mode=True,
            pipeline=test_pipeline,
            backend_args=None,
        ),
    )
    cfg.test_dataloader = cfg.val_dataloader
    cfg.val_evaluator = dict(
        type="CocoMetric",
        ann_file=f"{p.data_root}/annotations/val.json",
        metric="bbox",
        classwise=True,
        format_only=False,
        backend_args=None,
    )
    cfg.test_evaluator = cfg.val_evaluator

    switch = stage2_epochs(p.epochs)
    val_interval = 1 if p.epochs <= 50 else 5
    cfg.train_cfg = dict(type="EpochBasedTrainLoop", max_epochs=p.epochs, val_interval=val_interval)
    if val_interval > 1 and switch:
        cfg.train_cfg["dynamic_intervals"] = [(p.epochs - switch, 1)]

    lr = p.learning_rate or default_learning_rate(p.batch_size)
    iters_per_epoch = max(1, math.ceil(p.num_train_images / p.batch_size))
    total_iters = iters_per_epoch * p.epochs
    warmup_iters = int(max(1, min(1000, total_iters // 10)))
    cfg.optim_wrapper = dict(
        type="AmpOptimWrapper" if p.use_amp else "OptimWrapper",
        optimizer=dict(type="AdamW", lr=lr, weight_decay=0.05),
        paramwise_cfg=dict(norm_decay_mult=0, bias_decay_mult=0, bypass_duplicate=True),
        clip_grad=dict(max_norm=35, norm_type=2),
    )
    if p.use_amp:
        cfg.optim_wrapper["loss_scale"] = "dynamic"
    cosine_begin = p.epochs // 2
    cfg.param_scheduler = [
        dict(type="LinearLR", start_factor=1.0e-3, by_epoch=False, begin=0, end=warmup_iters),
        dict(type="CosineAnnealingLR", eta_min=lr * 0.05, begin=cosine_begin, end=p.epochs,
             T_max=max(1, p.epochs - cosine_begin), by_epoch=True, convert_to_iter_based=True),
    ]
    cfg.auto_scale_lr = dict(enable=False, base_batch_size=p.batch_size)

    custom_hooks = [
        dict(type="EMAHook", ema_type="ExpMomentumEMA", momentum=0.0002, update_buffers=True, priority=49),
    ]
    if switch:
        custom_hooks.append(dict(type="PipelineSwitchHook", switch_epoch=p.epochs - switch,
                                 switch_pipeline=train_pipeline_stage2))
    cfg.custom_hooks = custom_hooks
    cfg.default_hooks.checkpoint = dict(
        type="CheckpointHook", interval=val_interval, max_keep_ckpts=2, save_best="coco/bbox_mAP", rule="greater"
    )
    cfg.default_hooks.logger = dict(type="LoggerHook", interval=10)
    cfg.default_hooks.visualization = dict(type="DetVisualizationHook", draw=False)
    cfg.visualizer = dict(type="DetLocalVisualizer", vis_backends=[dict(type="LocalVisBackend")], name="visualizer")
    cfg.log_processor = dict(type="LogProcessor", window_size=10, by_epoch=True)
    cfg.load_from = p.load_from
    cfg.resume = False
    cfg.work_dir = p.work_dir
    cfg.randomness = dict(seed=p.seed, deterministic=False)
    cfg.launcher = "none"
    # TTA config from the base file is not used
    cfg.pop("tta_model", None)
    cfg.pop("tta_pipeline", None)
    return cfg
