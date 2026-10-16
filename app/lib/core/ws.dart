import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'api.dart';
import 'config.dart';
import 'session.dart';

/// Realtime channel: heartbeat (unread / guard / market state) and quote pushes.
class RealtimeState {
  final bool connected;
  final int unread;
  final String guardMode;
  final int openItems;
  final bool marketOpen;
  final Map<String, Map<String, dynamic>> quotes;
  const RealtimeState({this.connected = false, this.unread = 0, this.guardMode = 'NORMAL', this.openItems = 0, this.marketOpen = false, this.quotes = const {}});
  RealtimeState copyWith({bool? connected, int? unread, String? guardMode, int? openItems, bool? marketOpen, Map<String, Map<String, dynamic>>? quotes}) =>
      RealtimeState(connected: connected ?? this.connected, unread: unread ?? this.unread, guardMode: guardMode ?? this.guardMode, openItems: openItems ?? this.openItems, marketOpen: marketOpen ?? this.marketOpen, quotes: quotes ?? this.quotes);
}

class RealtimeNotifier extends Notifier<RealtimeState> {
  WebSocketChannel? _ch;
  Timer? _retry;
  int _backoff = 1;
  bool _disposed = false;
  int _gen = 0; // connection generation: callbacks from an old socket are ignored
  final Set<String> _subs = {};

  @override
  RealtimeState build() {
    ref.listen(sessionProvider, (prev, next) {
      if (next.authenticated && !(prev?.authenticated ?? false)) _connect();
      if (!next.authenticated) _close();
    });
    if (ref.read(sessionProvider).authenticated) Future.microtask(_connect);
    ref.onDispose(() {
      _disposed = true;
      _close();
    });
    return const RealtimeState();
  }

  void _connect() {
    if (_disposed) return;
    final token = ref.read(apiProvider).accessToken;
    if (token == null) return;
    _close();
    final gen = ++_gen;
    try {
      _ch = WebSocketChannel.connect(Uri.parse('${AppConfig.wsUrl}?token=$token'));
      state = state.copyWith(connected: true);
      if (_subs.isNotEmpty) _ch!.sink.add(jsonEncode({'action': 'subscribe', 'channels': _subs.toList()}));
      _ch!.stream.listen(_onMessage, onError: (_) => _scheduleRetry(gen), onDone: () => _scheduleRetry(gen));
      _backoff = 1;
    } catch (_) {
      _scheduleRetry(gen);
    }
  }

  void _scheduleRetry(int gen) {
    if (_disposed || gen != _gen) return; // closed on purpose or superseded
    Future.microtask(() {
      if (_disposed || gen != _gen) return;
      state = state.copyWith(connected: false);
      _retry?.cancel();
      _retry = Timer(Duration(seconds: _backoff), _connect);
      _backoff = (_backoff * 2).clamp(1, 30);
    });
  }

  void _onMessage(dynamic raw) {
    try {
      final m = (jsonDecode(raw as String) as Map).cast<String, dynamic>();
      final ch = m['ch']?.toString() ?? '';
      final data = (m['data'] as Map?)?.cast<String, dynamic>() ?? {};
      if (ch == 'system') {
        state = state.copyWith(unread: (data['unread'] as num?)?.toInt() ?? state.unread, guardMode: data['guard_mode']?.toString() ?? state.guardMode,
            openItems: (data['open_items'] as num?)?.toInt() ?? state.openItems, marketOpen: data['market_open'] == true);
      } else if (ch.startsWith('quotes:')) {
        state = state.copyWith(quotes: {...state.quotes, ch.substring(7): data});
      }
    } catch (_) {}
  }

  void subscribe(List<String> channels) {
    _subs.addAll(channels);
    _ch?.sink.add(jsonEncode({'action': 'subscribe', 'channels': channels}));
  }

  void _close() {
    _retry?.cancel();
    _retry = null;
    _gen++;
    _ch?.sink.close();
    _ch = null;
  }
}

final realtimeProvider = NotifierProvider<RealtimeNotifier, RealtimeState>(RealtimeNotifier.new);
