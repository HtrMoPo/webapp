import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'home', component: () => import('./views/HomeView.vue') },
  { path: '/catalog', name: 'catalog', component: () => import('./views/CatalogView.vue') },
  { path: '/models/:slug', name: 'model-detail', component: () => import('./views/ModelDetailView.vue'), props: true },
  { path: '/upload', name: 'upload', component: () => import('./views/ModelFormView.vue') },
  {
    path: '/models/:recordId/new-version',
    name: 'new-version',
    component: () => import('./views/ModelFormView.vue'),
    props: (route) => ({ recordId: Number(route.params.recordId) }),
  },
  { path: '/mine', name: 'my-models', component: () => import('./views/MyModelsView.vue') },
  { path: '/login', name: 'login', component: () => import('./views/LoginView.vue') },
]

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})
