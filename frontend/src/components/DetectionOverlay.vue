<template>
  <div class="detection-overlay">
    <img :src="src" class="full-width block" alt="" />
    <svg class="overlay" :viewBox="`0 0 ${result.image.width} ${result.image.height}`" preserveAspectRatio="none">
      <g v-for="(d, i) in result.detections" :key="i">
        <rect
          :x="d.bbox.x1"
          :y="d.bbox.y1"
          :width="d.bbox.x2 - d.bbox.x1"
          :height="d.bbox.y2 - d.bbox.y1"
          fill="none"
          :stroke="classInfo(d.class).color"
          stroke-width="2"
          vector-effect="non-scaling-stroke"
        />
        <text
          :x="d.bbox.x1 + 3"
          :y="Math.max(d.bbox.y1 - 5, 12)"
          :fill="classInfo(d.class).color"
          :font-size="Math.max(12, result.image.width / 90)"
          font-weight="bold"
          paint-order="stroke"
          stroke="black"
          stroke-width="3"
        >
          {{ classInfo(d.class).label }} {{ (d.confidence * 100).toFixed(0) }}%
        </text>
      </g>
    </svg>
  </div>
</template>

<script setup lang="ts">
import type { DetectResponse } from '@/services/api'
import { useClassesStore } from '@/stores/classes'

defineProps<{ src: string; result: DetectResponse }>()
const classes = useClassesStore()
const classInfo = (name: string) => classes.info(name)
</script>

<style scoped>
.detection-overlay {
  position: relative;
}
.overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
</style>
