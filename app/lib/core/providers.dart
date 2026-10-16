import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api.dart';
import 'format.dart';

/// Generic JSON fetchers keyed by path (+ query) so screens stay small. Invalidate by path to refresh.
final getProvider = FutureProvider.autoDispose.family<dynamic, String>((ref, path) async {
  final api = ref.watch(apiProvider);
  ref.keepAlive();
  return api.get(path);
});

final getMapProvider = FutureProvider.autoDispose.family<Map<String, dynamic>, String>((ref, path) async => asMap(await ref.watch(getProvider(path).future)));
final getListProvider = FutureProvider.autoDispose.family<List<Map<String, dynamic>>, String>((ref, path) async => asList(await ref.watch(getProvider(path).future)));

/// Selected horizon for list screens (persisted per session, seeded from user settings).
class HorizonNotifier extends Notifier<String> {
  @override
  String build() => 'MID';
  void set(String v) => state = v;
}

final horizonProvider = NotifierProvider<HorizonNotifier, String>(HorizonNotifier.new);

/// Symbol search for the command palette / add-to-watchlist.
final stockSearchProvider = FutureProvider.autoDispose.family<List<Map<String, dynamic>>, String>((ref, q) async {
  if (q.trim().isEmpty) return [];
  return asList(await ref.watch(apiProvider).get('/stocks', query: {'q': q.trim(), 'limit': 12}));
});
