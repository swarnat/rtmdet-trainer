import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from '@/layouts/MainLayout.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: MainLayout,
      children: [
        { path: '', name: 'dashboard', component: () => import('@/pages/DashboardPage.vue') },
        { path: 'annotate/:id?', name: 'annotate', component: () => import('@/pages/AnnotationPage.vue') },
        { path: 'training', name: 'training', component: () => import('@/pages/TrainingPage.vue') },
        { path: 'models', name: 'models', component: () => import('@/pages/ModelsPage.vue') },
        { path: 'classes', name: 'classes', component: () => import('@/pages/ClassesPage.vue') },
        { path: 'settings', name: 'settings', component: () => import('@/pages/SettingsPage.vue') },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
