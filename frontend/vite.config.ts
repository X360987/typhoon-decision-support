import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  build: {
    // The tree-shaken ECharts vendor chunk is ~560 kB and only loads with chart pages.
    chunkSizeWarningLimit: 600,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: 'echarts', test: /node_modules[\\/](echarts|zrender)[\\/]/ },
            { name: 'leaflet', test: /node_modules[\\/]leaflet[\\/]/ },
          ],
        },
      },
    },
  },
})
