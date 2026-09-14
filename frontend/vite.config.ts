import {defineConfig} from 'vite';
export default defineConfig({build:{rollupOptions:{input:{desktop:'index.html',remote:'remote.html'}}}});
