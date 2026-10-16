import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/session.dart';
import '../features/account/account_page.dart';
import '../features/account/coach_page.dart';
import '../features/admin/admin_shell.dart';
import '../features/ai/ai_page.dart';
import '../features/alerts/alerts_page.dart';
import '../features/auth/auth_pages.dart';
import '../features/market/market_page.dart';
import '../features/onboarding/onboarding_page.dart';
import '../features/portfolio/plan_page.dart';
import '../features/portfolio/portfolio_page.dart';
import '../features/screener/screener_page.dart';
import '../features/shell/app_shell.dart';
import '../features/stock/analysis_page.dart';
import '../features/watch/watch_page.dart';

/// Pure redirect logic (unit-testable): returns the path to go to, or null to stay.
String? computeRedirect({required bool loading, required bool authenticated, required String status, required bool needsOnboarding, required bool isAdmin, required String path}) {
  if (loading) return null;
  const public = {'/login', '/register', '/forgot-password', '/reset-password'};
  if (!authenticated) return public.contains(path) ? null : '/login?next=${Uri.encodeComponent(path)}';
  if (status != 'ACTIVE') return path == '/pending' ? null : '/pending';
  if (path == '/pending' || public.contains(path)) return needsOnboarding ? '/onboarding' : '/';
  if (needsOnboarding && path != '/onboarding') return '/onboarding';
  if (!needsOnboarding && path == '/onboarding') return '/';
  if (path.startsWith('/admin') && !isAdmin) return '/';
  return null;
}

class _SessionListenable extends ChangeNotifier {
  _SessionListenable(Ref ref) {
    ref.listen(sessionProvider, (_, __) => notifyListeners());
  }
}

final routerProvider = Provider<GoRouter>((ref) {
  final listenable = _SessionListenable(ref);
  return GoRouter(
    initialLocation: '/',
    refreshListenable: listenable,
    redirect: (context, state) {
      final s = ref.read(sessionProvider);
      return computeRedirect(loading: s.loading, authenticated: s.authenticated, status: s.status, needsOnboarding: s.needsOnboarding, isAdmin: s.isAdmin, path: state.uri.path);
    },
    routes: [
      GoRoute(path: '/login', builder: (c, s) => LoginPage(next: s.uri.queryParameters['next'])),
      GoRoute(path: '/register', builder: (c, s) => RegisterPage(invite: s.uri.queryParameters['invite'])),
      GoRoute(path: '/forgot-password', builder: (c, s) => const ForgotPage()),
      GoRoute(path: '/reset-password', builder: (c, s) => ResetPage(token: s.uri.queryParameters['token'])),
      GoRoute(path: '/pending', builder: (c, s) => const PendingPage()),
      GoRoute(path: '/onboarding', builder: (c, s) => const OnboardingPage()),
      GoRoute(path: '/admin', redirect: (c, s) => s.uri.path == '/admin' ? '/admin/overview' : null, routes: [
        GoRoute(path: ':section', builder: (c, s) => AdminShell(section: s.pathParameters['section']!)),
      ]),
      ShellRoute(
        builder: (context, state, child) => AppShell(location: state.uri.toString(), child: child),
        routes: [
          GoRoute(path: '/', builder: (c, s) => const MarketPage()),
          GoRoute(path: '/stocks/:symbol', builder: (c, s) => AnalysisPage(symbol: s.pathParameters['symbol']!.toUpperCase(), horizon: s.uri.queryParameters['hz'])),
          GoRoute(path: '/analysis', builder: (c, s) => const AnalysisLanding()),
          GoRoute(path: '/watch', builder: (c, s) => WatchPage(tab: s.uri.queryParameters['tab'], horizon: s.uri.queryParameters['hz'])),
          GoRoute(path: '/screener', builder: (c, s) => ScreenerPage(preset: s.uri.queryParameters['preset'])),
          GoRoute(path: '/screener/:id', builder: (c, s) => ScreenerPage(savedId: s.pathParameters['id'])),
          GoRoute(path: '/alerts', builder: (c, s) => AlertsPage(filter: s.uri.queryParameters['f'])),
          GoRoute(path: '/portfolio', builder: (c, s) => PortfolioPage(tab: s.uri.queryParameters['tab'])),
          GoRoute(path: '/portfolio/:id', builder: (c, s) => PortfolioPage(id: s.pathParameters['id'], tab: s.uri.queryParameters['tab'])),
          GoRoute(path: '/portfolio/:id/plans/:symbol', builder: (c, s) => PlanPage(portfolioId: s.pathParameters['id']!, symbol: s.pathParameters['symbol']!.toUpperCase())),
          GoRoute(path: '/plans/:symbol', builder: (c, s) => PlanPage(portfolioId: null, symbol: s.pathParameters['symbol']!.toUpperCase())),
          GoRoute(path: '/account', builder: (c, s) => AccountPage(section: s.uri.queryParameters['s'])),
          GoRoute(path: '/account/coach/:week', builder: (c, s) => CoachPage(week: s.pathParameters['week']!)),
          GoRoute(path: '/ai', builder: (c, s) => AiPage(conversationId: s.uri.queryParameters['c'], symbol: s.uri.queryParameters['symbol'], screen: s.uri.queryParameters['screen'])),
        ],
      ),
    ],
  );
});
