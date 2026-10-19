import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'config.dart';

class ApiException implements Exception {
  final int status;
  final String code;
  final String message;
  final Map<String, dynamic> details;
  ApiException(this.status, this.code, this.message, [this.details = const {}]);
  @override
  String toString() => message;
  bool get pretradeRequired => code == 'PRETRADE_REQUIRED';
}

/// Token storage: secure storage on mobile/desktop, shared_preferences on web.
class TokenStore {
  static const _s = FlutterSecureStorage();
  static Future<String?> read(String k) async {
    if (kIsWeb) return (await SharedPreferences.getInstance()).getString(k);
    try {
      return await _s.read(key: k);
    } catch (_) {
      return (await SharedPreferences.getInstance()).getString(k);
    }
  }

  static Future<void> write(String k, String? v) async {
    if (kIsWeb) {
      final p = await SharedPreferences.getInstance();
      v == null ? await p.remove(k) : await p.setString(k, v);
      return;
    }
    try {
      v == null ? await _s.delete(key: k) : await _s.write(key: k, value: v);
    } catch (_) {
      final p = await SharedPreferences.getInstance();
      v == null ? await p.remove(k) : await p.setString(k, v);
    }
  }
}

class ApiClient {
  late final Dio dio;
  String? accessToken;
  String? refreshToken;
  Completer<bool>? _refreshing;
  void Function()? onUnauthenticated;
  /// Admin console idle lock (ADMIN_SESSION_EXPIRED) / 2FA gate (ADMIN_2FA_REQUIRED) — the admin frame shows an overlay.
  void Function(String code)? onAdminGate;

  ApiClient() {
    dio = Dio(BaseOptions(baseUrl: AppConfig.apiBaseUrl, connectTimeout: const Duration(seconds: 20), receiveTimeout: const Duration(seconds: 60), headers: {'Accept': 'application/json'}));
    dio.interceptors.add(InterceptorsWrapper(
      onRequest: (o, h) {
        if (accessToken != null && !o.headers.containsKey('Authorization')) o.headers['Authorization'] = 'Bearer $accessToken';
        h.next(o);
      },
      onError: (e, h) async {
        final code = _code(e.response?.data);
        if (e.response?.statusCode == 401 && code == 'TOKEN_EXPIRED' && refreshToken != null && e.requestOptions.extra['retried'] != true) {
          final ok = await _refresh();
          if (ok) {
            final req = e.requestOptions;
            req.headers['Authorization'] = 'Bearer $accessToken';
            req.extra['retried'] = true;
            try {
              return h.resolve(await dio.fetch(req));
            } on DioException catch (e2) {
              return h.next(e2);
            }
          }
        }
        if (e.response?.statusCode == 403 && (code == 'ADMIN_SESSION_EXPIRED' || code == 'ADMIN_2FA_REQUIRED')) onAdminGate?.call(code!);
        if (e.response?.statusCode == 401 && (code == 'TOKEN_INVALID' || code == 'SESSION_REVOKED' || code == 'REFRESH_INVALID' || code == 'REFRESH_REUSED' || code == 'USER_NOT_FOUND')) {
          await setTokens(null, null);
          onUnauthenticated?.call();
        }
        h.next(e);
      },
    ));
  }

  static String? _code(dynamic data) => data is Map && data['error'] is Map ? data['error']['code']?.toString() : null;

  Future<void> load() async {
    accessToken = await TokenStore.read('access');
    refreshToken = await TokenStore.read('refresh');
  }

  Future<void> setTokens(String? a, String? r) async {
    accessToken = a;
    refreshToken = r;
    await TokenStore.write('access', a);
    await TokenStore.write('refresh', r);
  }

  Future<bool> _refresh() async {
    if (_refreshing != null) return _refreshing!.future;
    _refreshing = Completer<bool>();
    try {
      final r = await Dio(BaseOptions(baseUrl: AppConfig.apiBaseUrl)).post('/auth/refresh', data: {'refresh_token': refreshToken});
      await setTokens(r.data['access_token'], r.data['refresh_token']);
      _refreshing!.complete(true);
      return true;
    } catch (_) {
      await setTokens(null, null);
      onUnauthenticated?.call();
      _refreshing!.complete(false);
      return false;
    } finally {
      _refreshing = null;
    }
  }

  ApiException _wrap(DioException e) {
    final d = e.response?.data;
    if (d is Map && d['error'] is Map) {
      final err = (d['error'] as Map).cast<String, dynamic>();
      return ApiException(e.response?.statusCode ?? 0, err['code']?.toString() ?? 'ERROR', err['message']?.toString() ?? 'Có lỗi xảy ra', (err['details'] as Map?)?.cast<String, dynamic>() ?? const {});
    }
    if (e.type == DioExceptionType.connectionError || e.type == DioExceptionType.connectionTimeout) {
      return ApiException(0, 'NETWORK', 'Mất kết nối. Tự kết nối lại khi có mạng.');
    }
    return ApiException(e.response?.statusCode ?? 0, 'ERROR', e.message ?? 'Có lỗi xảy ra');
  }

  Future<dynamic> get(String path, {Map<String, dynamic>? query}) async {
    try {
      return (await dio.get(path, queryParameters: query)).data;
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  Future<dynamic> post(String path, {Object? data, Map<String, dynamic>? query}) async {
    try {
      return (await dio.post(path, data: data, queryParameters: query)).data;
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  Future<dynamic> put(String path, {Object? data, Map<String, dynamic>? query}) async {
    try {
      return (await dio.put(path, data: data, queryParameters: query)).data;
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  Future<dynamic> patch(String path, {Object? data, Map<String, dynamic>? query}) async {
    try {
      return (await dio.patch(path, data: data, queryParameters: query)).data;
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  Future<dynamic> delete(String path, {Map<String, dynamic>? query}) async {
    try {
      return (await dio.delete(path, queryParameters: query)).data;
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  Future<dynamic> upload(String path, List<int> bytes, String filename, {Map<String, dynamic>? query}) async {
    try {
      final form = FormData.fromMap({'file': MultipartFile.fromBytes(bytes, filename: filename)});
      return (await dio.post(path, data: form, queryParameters: query)).data;
    } on DioException catch (e) {
      throw _wrap(e);
    }
  }

  /// Server-sent events stream of JSON objects.
  Stream<Map<String, dynamic>> sse(String path, Map<String, dynamic> body) async* {
    final req = http.Request('POST', Uri.parse('${AppConfig.apiBaseUrl}$path'));
    req.headers['Content-Type'] = 'application/json';
    req.headers['Accept'] = 'text/event-stream';
    if (accessToken != null) req.headers['Authorization'] = 'Bearer $accessToken';
    req.body = jsonEncode(body);
    final client = http.Client();
    try {
      final res = await client.send(req);
      if (res.statusCode >= 400) {
        final txt = await res.stream.bytesToString();
        try {
          final m = jsonDecode(txt);
          throw ApiException(res.statusCode, m['error']['code'], m['error']['message']);
        } on ApiException {
          rethrow;
        } catch (_) {
          throw ApiException(res.statusCode, 'ERROR', 'Lỗi $txt');
        }
      }
      await for (final line in res.stream.transform(utf8.decoder).transform(const LineSplitter())) {
        if (!line.startsWith('data:')) continue;
        final payload = line.substring(5).trim();
        if (payload.isEmpty) continue;
        try {
          yield (jsonDecode(payload) as Map).cast<String, dynamic>();
        } catch (_) {}
      }
    } finally {
      client.close();
    }
  }
}

final apiProvider = Provider<ApiClient>((ref) => ApiClient());
