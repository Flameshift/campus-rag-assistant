<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

const canvasRef = ref(null)
let ctx = null
let rafId = 0
let stars = []
let pointer = { x: 0, y: 0 }
let width = 0
let height = 0

function resize() {
  const canvas = canvasRef.value
  if (!canvas) return
  const rect = canvas.parentElement.getBoundingClientRect()
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  width = rect.width
  height = rect.height
  canvas.width = Math.round(width * dpr)
  canvas.height = Math.round(height * dpr)
  canvas.style.width = `${width}px`
  canvas.style.height = `${height}px`
  ctx = canvas.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  const count = Math.min(220, Math.max(80, Math.floor((width * height) / 6500)))
  stars = Array.from({ length: count }, () => ({
    x: Math.random() * width,
    y: Math.random() * height,
    r: Math.random() * 1.4 + 0.4,
    speedX: (Math.random() - 0.5) * 0.12,
    speedY: (Math.random() - 0.5) * 0.1,
    phase: Math.random() * Math.PI * 2,
    red: Math.random() > 0.6
  }))
}

function draw() {
  if (!ctx) return
  ctx.clearRect(0, 0, width, height)
  const time = performance.now() / 1000
  const maxDistance = Math.min(width, height) * 0.14

  for (const star of stars) {
    star.x += star.speedX
    star.y += star.speedY
    if (star.x < -10) star.x = width + 10
    if (star.x > width + 10) star.x = -10
    if (star.y < -10) star.y = height + 10
    if (star.y > height + 10) star.y = -10

    const twinkle = 0.55 + 0.45 * Math.sin(time * 1.6 + star.phase)
    ctx.beginPath()
    ctx.fillStyle = star.red ? `rgba(161, 29, 46, ${twinkle})` : `rgba(242, 168, 176, ${twinkle})`
    ctx.arc(star.x + pointer.x * 14, star.y + pointer.y * 10, star.r, 0, Math.PI * 2)
    ctx.fill()
  }

  ctx.lineWidth = 0.5
  for (let i = 0; i < stars.length; i += 1) {
    for (let j = i + 1; j < stars.length; j += 1) {
      const a = stars[i]
      const b = stars[j]
      const dx = a.x - b.x
      const dy = a.y - b.y
      const dist = Math.hypot(dx, dy)
      if (dist < maxDistance) {
        ctx.strokeStyle = `rgba(161, 29, 46, ${0.12 * (1 - dist / maxDistance)})`
        ctx.beginPath()
        ctx.moveTo(a.x, a.y)
        ctx.lineTo(b.x, b.y)
        ctx.stroke()
      }
    }
  }

  rafId = window.requestAnimationFrame(draw)
}

function onPointerMove(event) {
  const rect = canvasRef.value.parentElement.getBoundingClientRect()
  pointer.x = (event.clientX - rect.left) / rect.width - 0.5
  pointer.y = (event.clientY - rect.top) / rect.height - 0.5
}

function onPointerLeave() {
  pointer.x = 0
  pointer.y = 0
}

onMounted(() => {
  resize()
  draw()
  window.addEventListener('resize', resize)
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerleave', onPointerLeave)
})

onBeforeUnmount(() => {
  window.cancelAnimationFrame(rafId)
  window.removeEventListener('resize', resize)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerleave', onPointerLeave)
})
</script>

<template>
  <canvas ref="canvasRef" class="hero-starfield"></canvas>
</template>

<style scoped>
.hero-starfield {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: block;
  pointer-events: none;
}
</style>
