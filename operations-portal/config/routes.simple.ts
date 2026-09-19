export default [
  {
    path: '/user',
    layout: false,
    routes: [
      {
        name: '登录',
        path: '/user/login',
        component: './user/login',
      },
    ],
  },
  {
    path: '/welcome',
    name: '欢迎',
    icon: 'smile',
    component: './Welcome',
  },
  {
    path: '/',
    name: '管理页',
    icon: 'crown',
    access: 'canAdmin',
    routes: [
      {
        path: '/',
        redirect: '/overview',
      },
      {
        path: '/overview',
        name: '二级管理页',
        component: './Admin',
      },
    ],
  },
  {
    name: '查询表格',
    icon: 'table',
    path: '/list',
    component: './table-list',
  },
  {
    path: '/',
    redirect: '/welcome',
  },
  {
    component: './exception/404',
    layout: false,
    path: './*',
  },
];
