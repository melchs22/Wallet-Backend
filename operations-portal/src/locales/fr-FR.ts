import component from './en-US/component';
import globalHeader from './en-US/globalHeader';
import network from './en-US/network';
import pages from './en-US/pages';
import settingDrawer from './en-US/settingDrawer';
import settings from './en-US/settings';

export default {
  'navBar.lang': 'Langue',
  'layout.user.link.help': 'Aide',
  'layout.user.link.privacy': 'Confidentialite',
  'layout.user.link.terms': 'Conditions',
  'menu.login': 'Connexion',
  'menu.admin': 'Administration DSD',
  'menu.admin.overview': 'Vue d ensemble',
  'menu.admin.users': 'Utilisateurs',
  'menu.admin.wallets': 'Portefeuilles',
  'menu.admin.transactions': 'Transactions',
  'menu.admin.push-devices': 'Appareils push',
  'menu.admin.trusted-devices': 'Appareils de confiance',
  'menu.admin.parental-controls': 'Controle parental',
  'menu.admin.requests': 'Demandes de paiement',
  'menu.admin.splits': 'Partages de factures',
  'menu.admin.attempts': 'Tentatives de transfert',
  'menu.admin.audit': 'Journal d audit',
  'menu.admin.settings': 'Parametres plateforme',
  'menu.admin.tasks': 'Taches planifiees',
  'menu.admin.support': 'Support',
  'menu.admin.kyc': 'Revue KYC',
  'menu.admin.mobile-money': 'Mobile money',
  'menu.admin.webhooks': 'Webhooks echoues',
  'menu.admin.fee-rules': 'Regles de frais',
  'menu.admin.rates': 'Taux de change',
  'menu.admin.team': 'Equipe admin',
  'menu.admin.disputes': 'Litiges',
  'menu.admin.merchants': 'Marchands',
  ...globalHeader,
  ...settingDrawer,
  ...settings,
  ...network,
  ...component,
  ...pages,
};
