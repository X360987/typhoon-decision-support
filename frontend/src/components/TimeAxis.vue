<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { addHours, fmtTime, hourFloor, hoursBetween } from '../lib/format'

const props = defineProps<{
  start: string
  end: string
  modelValue: string | null
  playbackTarget?: HTMLElement | null
}>()
const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>()

const BASE_STEP_MS = 720
const playing = ref(false)
const speed = ref(1)
let timer: number | null = null

const total = computed(() => Math.max(0, hoursBetween(hourFloor(props.start), hourFloor(props.end))))
const index = computed(() =>
  props.modelValue ? Math.min(total.value, Math.max(0, hoursBetween(hourFloor(props.start), props.modelValue))) : 0,
)
const progress = computed(() => total.value ? index.value / total.value * 100 : 0)

function setIndex(i: number) {
  const clamped = Math.min(total.value, Math.max(0, i))
  emit('update:modelValue', addHours(hourFloor(props.start), clamped))
}

function step(delta: number) {
  setIndex(index.value + delta)
}

function stop() {
  playing.value = false
  if (timer != null) window.clearInterval(timer)
  timer = null
}

function play() {
  if (index.value >= total.value) setIndex(0)
  playing.value = true
  if (timer != null) window.clearInterval(timer)
  timer = window.setInterval(() => {
    if (index.value >= total.value) stop()
    else step(1)
  }, BASE_STEP_MS / speed.value)
}

function toggle() {
  if (playing.value) stop()
  else play()
}

watch(speed, () => {
  if (playing.value) play()
})

onBeforeUnmount(stop)

defineExpose({ stop })
</script>

<template>
  <div class="axis" role="group" aria-label="分析时间轴">
    <Teleport :to="playbackTarget || 'body'" :disabled="!playbackTarget">
      <div class="playback" role="group" aria-label="播放与当前时刻">
        <button
          type="button"
          class="btn play"
          :aria-label="playing ? '暂停回放' : '开始回放'"
          :aria-pressed="playing"
          @click="toggle"
        >
          <span aria-hidden="true">{{ playing ? '❚❚' : '▶' }}</span>
        </button>
        <div class="now">
          <div class="time num">{{ fmtTime(modelValue, false) }}</div>
          <div class="muted small">{{ fmtTime(modelValue).slice(0, 10) }}</div>
        </div>
      </div>
    </Teleport>
    <button type="button" class="btn" aria-label="后退一小时" @click="step(-1)">‹ 1h</button>
    <div class="range">
      <input
        class="slider"
        type="range"
        :min="0"
        :max="total"
        :value="index"
        :style="{ '--progress': `${progress}%` }"
        :aria-valuetext="fmtTime(modelValue)"
        aria-label="回放时刻"
        @input="setIndex(Number(($event.target as HTMLInputElement).value))"
      />
      <div class="range-times muted small" aria-hidden="true">
        <span>{{ fmtTime(start).slice(5) }}</span>
        <span>{{ fmtTime(end).slice(5) }}</span>
      </div>
    </div>
    <button type="button" class="btn" aria-label="前进一小时" @click="step(1)">1h ›</button>
    <div class="seg" role="group" aria-label="倍速">
      <button v-for="s in [1, 2, 4]" :key="s" type="button" :class="{ on: speed === s }" :aria-pressed="speed === s" @click="speed = s">{{ s }}x</button>
    </div>
  </div>
</template>

<style scoped>
.axis {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: var(--control-radius);
  background: color-mix(in oklab, var(--control-bg) 88%, var(--surface));
}
.playback {
  display: flex;
  align-items: center;
  flex: none;
  gap: 9px;
}
.play {
  justify-content: center;
  width: 38px;
  height: 38px;
  padding: 0;
  flex: none;
  border-color: color-mix(in oklab, var(--accent) 36%, transparent);
  background: var(--control-selected);
  color: var(--control-selected-text);
  font-size: 15px;
}
.play[aria-pressed='true'] {
  border-color: var(--accent);
  background: var(--accent);
  color: var(--on-accent);
  box-shadow: 0 0 16px rgba(56, 189, 248, 0.3);
}
.play[aria-pressed='true']:hover {
  background: var(--accent-hover);
  color: var(--on-accent);
}
.now {
  min-width: 72px;
}
.time {
  font-family: var(--font-mono);
  font-size: 19px;
  font-weight: 650;
  line-height: 1.18;
  letter-spacing: -0.02em;
}
.range {
  flex: 1;
  min-width: 84px;
}
.slider {
  --track-fill: linear-gradient(90deg, var(--accent) var(--progress), rgba(255, 255, 255, 0.14) var(--progress));
  appearance: none;
  display: block;
  width: 100%;
  height: 24px;
  margin: 0;
  background: transparent;
  cursor: pointer;
}
.slider::-webkit-slider-runnable-track {
  height: 4px;
  border-radius: 999px;
  background: var(--track-fill);
}
.slider::-moz-range-track {
  height: 4px;
  border-radius: 999px;
  background: var(--track-fill);
}
.slider::-webkit-slider-thumb {
  appearance: none;
  width: 12px;
  height: 12px;
  margin-top: -4px;
  border: 2px solid var(--bg);
  border-radius: 50%;
  background: var(--line-active);
  box-shadow: 0 0 8px rgba(56, 189, 248, 0.6);
}
.slider::-moz-range-thumb {
  width: 10px;
  height: 10px;
  border: 2px solid var(--bg);
  border-radius: 50%;
  background: var(--line-active);
  box-shadow: 0 0 8px rgba(56, 189, 248, 0.6);
}
.range-times {
  display: flex;
  justify-content: space-between;
  gap: 4px;
  font-family: var(--font-mono);
  font-size: 10px;
  white-space: nowrap;
}
@media (max-width: 760px) {
  .axis {
    flex-wrap: wrap;
    padding-inline: 8px;
    gap: 4px;
  }
  .axis .seg button {
    padding-inline: 7px;
    font-size: 12px;
  }
  .axis .btn {
    padding-inline: 5px;
  }
  .range {
    order: 1;
    flex-basis: 100%;
  }
  .slider {
    height: 32px;
  }
}
</style>
