import 'package:flutter/material.dart';
import 'package:flutter_web_plugins/url_strategy.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'app/router.dart';
import 'core/session.dart';
import 'core/theme.dart';
import 'core/ws.dart';

Future<void> main() async {
  usePathUrlStrategy(); // /stocks/FPT instead of /#/stocks/FPT on the web
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('vi');
  runApp(const ProviderScope(child: VinatradeApp()));
}

class VinatradeApp extends ConsumerWidget {
  const VinatradeApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    final session = ref.watch(sessionProvider);
    ref.watch(realtimeProvider); // keep the socket alive app-wide
    final mode = switch (session.theme) { 'light' => ThemeMode.light, 'system' => ThemeMode.system, _ => ThemeMode.dark };
    return MaterialApp.router(
      title: 'Vinatrade',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(Brightness.light),
      darkTheme: buildTheme(Brightness.dark),
      themeMode: mode,
      routerConfig: router,
      locale: const Locale('vi'),
      supportedLocales: const [Locale('vi'), Locale('en')],
      localizationsDelegates: const [GlobalMaterialLocalizations.delegate, GlobalWidgetsLocalizations.delegate, GlobalCupertinoLocalizations.delegate],
      builder: (context, child) => MediaQuery(data: MediaQuery.of(context).copyWith(disableAnimations: MediaQuery.of(context).disableAnimations || session.reduceMotion), child: child!),
    );
  }
}
