"""RTMDet head that does not punish detections inside ignore regions.

MMDetection reads ``iscrowd`` boxes as ignore regions (``data_sample.ignored_instances``) and hands
them to the head, but RTMDet's assigner accepts ``gt_instances_ignore`` without using it: the cells
inside such a region would still be trained as background. Here the classification loss weight of
those cells is set to 0 instead. Cells that were assigned to a real box stay positive, so an object
that overlaps an ignore region is still learned.
"""
from __future__ import annotations

from mmdet.models.dense_heads import RTMDetSepBNHead
from mmdet.registry import MODELS

from .ignore_regions import mute_background


@MODELS.register_module()
class IgnoreRTMDetSepBNHead(RTMDetSepBNHead):
    def _get_targets_single(self, cls_scores, bbox_preds, flat_anchors, valid_flags, gt_instances, img_meta,
                            gt_instances_ignore=None, unmap_outputs=True):
        targets = super()._get_targets_single(cls_scores, bbox_preds, flat_anchors, valid_flags, gt_instances, img_meta,
                                              gt_instances_ignore, unmap_outputs)
        if gt_instances_ignore is None or len(gt_instances_ignore) == 0 or targets[0] is None:
            return targets
        anchors, labels, label_weights, *rest = targets
        regions = gt_instances_ignore.bboxes
        regions = getattr(regions, "tensor", regions).to(anchors.device)
        # priors are (x, y, stride_w, stride_h) points
        label_weights = mute_background(label_weights, labels, anchors[:, :2], regions, self.num_classes)
        return (anchors, labels, label_weights, *rest)
