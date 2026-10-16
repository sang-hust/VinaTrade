/// Build-time configuration. Override with --dart-define=API_BASE_URL=...
class AppConfig {
  static const apiBaseUrl = String.fromEnvironment('API_BASE_URL', defaultValue: 'http://localhost:8010/api/v1');
  static String get wsUrl => apiBaseUrl.replaceFirst('http', 'ws').replaceFirst(RegExp(r'/api/v1$'), '/api/v1/ws');
  static const appName = 'Vinatrade';
  static const disclaimer = 'Thông tin chỉ mang tính tham khảo, không phải lời khuyên mua bán. Bạn tự chịu trách nhiệm với quyết định đầu tư.';
}
