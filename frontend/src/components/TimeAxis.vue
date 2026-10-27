<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { addHours, fmtTime, hourFloor, hoursBetween } from '../lib/format'

const props = defineProps<{
  start: string
  end: string
  modelValue: string | null
}>()
const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>()

const playing = ref(false)
const speed = ref(1)
let timer: number | null = null

const total = computed(() => Math.max(0, hoursBetween(hourFloor(props.start), hourFloor(props.end))))
const index = computed(() =>
  props.modelValue ? Math.min(total.value, Math.max(0, hoursBetween(hourFloor(props.start), props.modelValue))) : 0,
)

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
  }, 1200 / speed.value)
}

function toggle() {
  if (playing.value) stop()
  else play()
}

watch(speed, () => {
  if (playing.value) play()
})

onBeforeUnmount(stop)

function onKey(e: KeyboardEvent) {
  if (e.key === ' ') {
    e.preventDefault()
    toggle()
  }
}

defineExpose({ stop })
</script>

<template>
  <div class="axis" @keydown="onKey">
    <button
      type="button"
      class="play"
      :aria-label="playing ? '暂停回放' : '开始回放'"
      :aria-pressed="playing"
      @click="toggle"
    >
      <span v-if="playing">❚❚</span>
      <span v-else>▶</span>
    </button>
    <div class="now">
      <div class="time num">{{ fmtTime(modelValue, false) }}</div>
      <div class="muted small">{{ fmtTime(modelValue).slice(0, 10) }}</div>
    </div>
    <button type="button" class="btn ghost" aria-label="后退一小时" @click="step(-1)">‹ 1h</button>
    <input
      class="slider"
      type="range"
      :min="0"
      :max="total"
      :value="index"
      :aria-valuetext="fmtTime(modelValue)"
      aria-label="回放时刻"
      @input="setIndex(Number(($event.target as HTMLInputElement).value))"
    />
    <button type="button" class="btn ghost" aria-label="前进一小时" @click="step(1)">1h ›</button>
    <div class="seg" role="group" aria-label="倍速">
      <button v-for="s in [1, 2, 4]" :key="s" type="button" :class="{ on: speed === s }" @click="speed = s">{{ s }}x</button>
    </div>
  </div>
</template>

<style scoped>
.axis {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 0;
}
.play {
  width: 48px;
  height: 48px;
  flex: none;
  border-radius: 50%;
  border: 0;
  background: #1e3a8a;
  color: #fff;
  font-size: 16px;
  cursor: pointer;
}
.now {
  min-width: 92px;
}
.time {
  font-size: 22px;
  font-weight: 650;
}
.slider {
  flex: 1;
  min-width: 120px;
  accent-color: var(--accent);
}
@media (max-width: 760px) {
  .axis {
    flex-wrap: wrap;
  }
}
</style>
