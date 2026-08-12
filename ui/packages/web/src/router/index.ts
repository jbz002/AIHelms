import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory('/'),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('../views/Login.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/auth/callback',
      name: 'AuthCallback',
      component: () => import('../views/Callback.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/',
      component: () => import('../layouts/WebLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        { path: '', name: 'Identity', component: () => import('../views/MyIdentityView.vue') },
        { path: 'market', name: 'Market', component: () => import('../views/MarketView.vue') },
        {
          path: 'market/:type/:id',
          name: 'ResourceDetail',
          component: () => import('../views/ResourceDetailView.vue'),
        },
        { path: 'models', name: 'Models', component: () => import('../views/ModelSquare.vue') },
        { path: 'my-keys', name: 'ApiKeys', component: () => import('../views/ApiKeyView.vue') },
        { path: 'contributor', name: 'Contributor', component: () => import('../views/ContributorView.vue') },
        { path: 'docs', name: 'DocsLibraryList', component: () => import('../views/DocsCenterView.vue') },
        { path: 'docs/:libraryName', name: 'DocsDocumentList', component: () => import('../views/docs/DocumentListView.vue') },
        { path: 'docs/:libraryName/interfaces', name: 'DocsLibraryInterfaces', component: () => import('../views/docs/LibraryInterfacesView.vue') },
        { path: 'docs/:libraryName/documents/:docId', name: 'DocsDocumentDetail', component: () => import('../views/docs/DocumentDetailView.vue') },
        { path: 'docs/:libraryName/documents/:docId/interfaces', name: 'DocsDocumentInterfaces', component: () => import('../views/docs/DocumentInterfacesView.vue') },
        { path: 'agents', redirect: { name: 'Market' } },
      ],
    },
  ],
})

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('aihelms_token')
  // 从 AI Hub 跳转带 ?ticket=（无本地 token 时）：转交 AuthCallback 换 token，避免直接落 /login 丢 ticket
  const ticket = to.query.ticket
  if (typeof ticket === 'string' && ticket && !token && to.name !== 'AuthCallback') {
    next({ name: 'AuthCallback', query: { ticket } })
    return
  }
  if (to.meta.requiresAuth !== false && !token) {
    next({ name: 'Login' })
    return
  }
  if (to.name === 'Login' && token) {
    next({ name: 'Identity' })
    return
  }
  next()
})

export default router