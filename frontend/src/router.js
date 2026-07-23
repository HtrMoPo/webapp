import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'home', component: () => import('./views/HomeView.vue') },
  { path: '/catalog', name: 'catalog', component: () => import('./views/CatalogView.vue') },
  {
    path: '/models/:doiSlug/:titleSlug?',
    name: 'model-detail',
    component: () => import('./views/ModelDetailView.vue'),
    // titleSlug is purely cosmetic (SEO/readability) -- the component only
    // ever reads doiSlug, which is the actual lookup key.
    props: (route) => ({ doiSlug: route.params.doiSlug }),
  },
  {
    path: '/models/:doiSlug/playground',
    name: 'playground',
    component: () => import('./views/PlaygroundView.vue'),
    props: true,
  },
  { path: '/upload', name: 'upload', component: () => import('./views/ModelFormView.vue') },
  {
    path: '/models/:recordId/new-version',
    name: 'new-version',
    component: () => import('./views/ModelFormView.vue'),
    props: (route) => ({ recordId: Number(route.params.recordId) }),
  },
  { path: '/mine', name: 'my-models', component: () => import('./views/MyModelsView.vue') },
  { path: '/admin/playground', name: 'playground-admin', component: () => import('./views/PlaygroundAdminView.vue') },
  { path: '/login', name: 'login', component: () => import('./views/LoginView.vue') },
]

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})
