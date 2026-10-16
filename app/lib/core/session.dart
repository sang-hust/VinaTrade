import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api.dart';
import 'format.dart';

/// Authenticated session: tokens + /me payload. Drives router redirects and global UI state (guard mode, unread).
class SessionState {
  final bool loading;
  final bool authenticated;
  final Map<String, dynamic>? me;
  final String? error;
  const SessionState({this.loading = true, this.authenticated = false, this.me, this.error});

  Map<String, dynamic> get user => asMap(me?['user']);
  Map<String, dynamic> get settings => asMap(me?['settings']);
  Map<String, dynamic> get riskLimits => asMap(me?['risk_limits']);
  Map<String, dynamic> get guard => asMap(me?['guard']);
  String get status => asStr(user['status']) ?? 'PENDING';
  bool get isActive => authenticated && status == 'ACTIVE';
  bool get isAdmin => asStr(user['role']) == 'ADMIN';
  bool get needsOnboarding => me?['needs_onboarding'] == true;
  String get uiDetail => asStr(settings['ui_detail']) ?? 'STANDARD';
  String get horizon => asStr(settings['default_horizon']) ?? 'MID';
  bool get defensive => asStr(guard['mode']) == 'DEFENSIVE';
  bool get reduceMotion => settings['reduce_motion'] == true;
  int get unread => asInt(me?['unread_alerts']) ?? 0;
  int get aiLeft => asInt(me?['ai_questions_left']) ?? 0;
  String get theme => asStr(settings['theme']) ?? 'dark';

  SessionState copyWith({bool? loading, bool? authenticated, Map<String, dynamic>? me, String? error, bool clearMe = false}) =>
      SessionState(loading: loading ?? this.loading, authenticated: authenticated ?? this.authenticated, me: clearMe ? null : (me ?? this.me), error: error);
}

class SessionNotifier extends Notifier<SessionState> {
  late ApiClient api;

  @override
  SessionState build() {
    api = ref.read(apiProvider);
    api.onUnauthenticated = () => state = const SessionState(loading: false, authenticated: false);
    Future.microtask(_init);
    return const SessionState();
  }

  Future<void> _init() async {
    await api.load();
    if (api.accessToken == null) {
      state = const SessionState(loading: false, authenticated: false);
      return;
    }
    await refreshMe(silent: true);
  }

  Future<void> refreshMe({bool silent = false}) async {
    try {
      final me = asMap(await api.get('/me'));
      state = SessionState(loading: false, authenticated: true, me: me);
    } on ApiException catch (e) {
      if (e.status == 401 || e.code == 'NETWORK' && state.me == null) {
        state = SessionState(loading: false, authenticated: e.code == 'NETWORK' ? false : false, error: e.message);
      } else {
        state = state.copyWith(loading: false, authenticated: true, error: silent ? null : e.message);
      }
    } catch (e) {
      state = state.copyWith(loading: false, error: e.toString());
    }
  }

  Future<void> _applyTokens(dynamic data) async {
    await api.setTokens(data['access_token'], data['refresh_token']);
    await refreshMe();
  }

  Future<void> login(String email, String password, {String? totp}) async {
    final data = await api.post('/auth/login', data: {'email': email, 'password': password, if (totp != null) 'totp': totp, 'platform': _platform(), 'device_name': _deviceName()});
    await _applyTokens(data);
  }

  Future<void> register({required String email, required String password, required String fullName, String? phone, String? invite}) async {
    final data = await api.post('/auth/register', data: {'email': email, 'password': password, 'full_name': fullName, 'phone': phone, 'invite_code': invite, 'platform': _platform(), 'device_name': _deviceName()});
    await _applyTokens(data);
  }

  Future<void> logout() async {
    try {
      await api.post('/auth/logout');
    } catch (_) {}
    await api.setTokens(null, null);
    state = const SessionState(loading: false, authenticated: false);
  }

  Future<void> updateSettings(Map<String, dynamic> patch) async {
    final s = asMap(await api.patch('/me/settings', data: patch));
    state = state.copyWith(me: {...?state.me, 'settings': s});
  }

  void patchLocal(Map<String, dynamic> patch) => state = state.copyWith(me: {...?state.me, ...patch});

  static String _platform() {
    if (kIsWeb) return 'web';
    return switch (defaultTargetPlatform) { TargetPlatform.android => 'android', TargetPlatform.iOS => 'ios', TargetPlatform.windows => 'windows', TargetPlatform.macOS => 'macos', _ => 'web' };
  }

  static String _deviceName() => kIsWeb ? 'Trình duyệt' : defaultTargetPlatform.name;
}

final sessionProvider = NotifierProvider<SessionNotifier, SessionState>(SessionNotifier.new);

/// UI detail gate helper.
int detailRank(String level) => switch (level) { 'SIMPLE' => 0, 'STANDARD' => 1, 'FULL' => 2, _ => 1 };
