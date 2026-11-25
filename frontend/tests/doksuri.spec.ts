import { expect, it } from 'vitest'
import { DOKSURI_OVERLAY, locateTrackTime } from '../src/lib/doksuri'

it('locates an hourly Beijing metric time on the published six-hour path', () => {
  const { track } = DOKSURI_OVERLAY
  const position = locateTrackTime(track, '2023-07-28T10:00:00')
  expect(position?.from.time).toBe('2023-07-28T00:00:00.000Z')
  expect(position?.to.time).toBe('2023-07-28T06:00:00.000Z')
  expect(position?.fraction).toBeCloseTo(1 / 3)

  const exact = locateTrackTime(track, '2023-07-28T08:00:00+08:00')
  expect(exact?.from).toBe(exact?.to)
  expect(exact?.from.time).toBe('2023-07-28T00:00:00.000Z')
  expect(locateTrackTime(track, '2023-07-20T19:00:00')).toBeUndefined()
  expect(locateTrackTime(track, '2023-07-29T09:00:00')).toBeUndefined()
})
