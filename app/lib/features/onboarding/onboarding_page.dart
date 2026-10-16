import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api.dart';
import '../../core/format.dart';
import '../../core/providers.dart';
import '../../core/responsive.dart';
import '../../core/session.dart';
import '../../core/theme.dart';
import '../../shared/widgets/common.dart';

class OnboardingPage extends ConsumerStatefulWidget {
  const OnboardingPage({super.key});
  @override
  ConsumerState<OnboardingPage> createState() => _OnboardingPageState();
}

class _OnboardingPageState extends ConsumerState<OnboardingPage> {
  String experience = 'MID', holding = 'WEEKS', maxLoss = 'P8';
  String? capital;
  final Set<String> symbols = {};
  int step = 0; // phone: one question per screen
  bool _busy = false;
  final _search = TextEditingController();

  static const suggested = ['FPT', 'HPG', 'VCB', 'MWG', 'VNM', 'ACB', 'SSI', 'PNJ', 'DGC', 'CTR'];

  Map<String, String> get summary {
    final hz = {'DAYS': 'Ngắn hạn', 'WEEKS': 'Trung hạn', 'YEARS': 'Dài hạn'}[holding]!;
    final (stop, risk) = {'P5': ('5%', '1,0%'), 'P8': ('8%', '1,5%'), 'P10': ('10%', '2,0%')}[maxLoss]!;
    final detail = {'NEW': 'Đơn giản', 'MID': 'Vừa đủ', 'PRO': 'Đầy đủ'}[experience]!;
    final cap = {'LT200M': '150 tr', '200M_1B': '500 tr', '1B_3B': '2 tỷ', 'GT3B': '5 tỷ'}[capital] ?? 'theo tổng tài sản danh mục';
    return {'Khung mặc định': '$hz, cảnh báo cuối ngày${holding == 'DAYS' ? ' và trong phiên' : ''}', 'Mức cắt lỗ': stop, 'Rủi ro mỗi lệnh': risk, 'Cầu dao': '−3%/tuần, −6%/tháng', 'Mức chi tiết': detail, 'Vốn tính khối lượng': cap};
  }

  Future<void> _save() async {
    setState(() => _busy = true);
    try {
      final me = await ref.read(apiProvider).put('/me/onboarding', data: {'experience': experience, 'holding': holding, 'max_loss': maxLoss, 'symbols': symbols.toList(), 'capital_band': capital ?? 'SKIP'});
      ref.read(sessionProvider.notifier).patchLocal(asMap(me));
      if (mounted) {
        showToast(context, 'Đã lưu cài đặt. Chúc bạn đầu tư kỷ luật!');
        context.go('/');
      }
    } on ApiException catch (e) {
      if (mounted) showToast(context, e.message, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _skip() async {
    try {
      await ref.read(apiProvider).post('/me/onboarding/skip');
    } catch (_) {}
    ref.read(sessionProvider.notifier).patchLocal({'needs_onboarding': false});
    if (mounted) context.go('/');
  }

  @override
  Widget build(BuildContext context) {
    final c = context.vn;
    final name = ref.watch(sessionProvider).user['full_name']?.toString().split(' ').last ?? '';
    final questions = <Widget>[
      _q('1. Bạn đã đầu tư bao lâu?', [('NEW', 'Mới bắt đầu', 'Dưới 1 năm — giao diện gọn, kết luận trước'), ('MID', '1 đến 3 năm', 'Thêm chỉ báo và điểm thành phần'), ('PRO', 'Trên 3 năm', 'Mọi chỉ báo, bảng đợt tăng, bộ lọc nâng cao')], experience, (v) => setState(() => experience = v)),
      _q('2. Bạn thường giữ một mã bao lâu?', [('DAYS', 'Vài ngày', 'Ngắn hạn — ưu tiên kỹ thuật, cảnh báo trong phiên'), ('WEEKS', 'Vài tuần đến vài tháng', 'Trung hạn — cân bằng kỹ thuật và cơ bản'), ('YEARS', 'Trên một năm', 'Dài hạn — ưu tiên doanh nghiệp tốt, giá hợp lý')], holding, (v) => setState(() => holding = v)),
      _q('3. Chấp nhận lỗ tối đa cho một mã?', [('P5', 'Khoảng 5%', 'Cắt lỗ chặt, rủi ro 1% vốn mỗi lệnh'), ('P8', '7 đến 8%', 'Mặc định — rủi ro 1,5% vốn mỗi lệnh'), ('P10', 'Khoảng 10%', 'Rộng hơn, rủi ro 2% vốn mỗi lệnh')], maxLoss, (v) => setState(() => maxLoss = v)),
      _symbolsQ(),
      _q('5. Số vốn dùng để đầu tư?', [('LT200M', 'Dưới 200 triệu', ''), ('200M_1B', '200 triệu – 1 tỷ', ''), ('1B_3B', '1 – 3 tỷ', ''), ('GT3B', 'Trên 3 tỷ', ''), ('SKIP', 'Bỏ qua', 'Tính theo tổng tài sản danh mục')], capital ?? 'SKIP', (v) => setState(() => capital = v == 'SKIP' ? null : v)),
    ];
    final summaryCard = AppCard(
      color: c.surface2,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Cấu hình đề xuất', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 10),
        for (final e in summary.entries)
          Padding(padding: const EdgeInsets.only(bottom: 8), child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [SizedBox(width: 140, child: Text(e.key, style: TextStyle(color: c.muted, fontSize: 13))), Expanded(child: AnimatedSwitcher(duration: 250.ms, child: Text(e.value, key: ValueKey(e.value), style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13))))])),
        const SizedBox(height: 4),
        Text('Bạn sửa lại được bất cứ lúc nào ở Tài khoản.', style: TextStyle(color: c.faint, fontSize: 12)),
      ]),
    );
    final header = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Expanded(child: Text('Chào $name, bạn đầu tư theo cách nào?', style: Theme.of(context).textTheme.titleLarge)),
        TextButton(onPressed: _skip, child: const Text('Bỏ qua, dùng cài đặt mặc định')),
      ]),
      Text('5 câu trả lời giúp Vinatrade chọn khung thời gian, mức cắt lỗ, giới hạn rủi ro và độ chi tiết của giao diện.', style: TextStyle(color: c.muted)),
      const SizedBox(height: 14),
      _progress(context, ['Đăng ký ✓', 'Admin kích hoạt ✓', 'Hồ sơ đầu tư', 'Bắt đầu dùng'], 2),
      const SizedBox(height: 20),
    ]);
    if (context.isPhone) {
      return Scaffold(
        appBar: AppBar(title: Text('Câu ${step + 1}/5'), actions: [TextButton(onPressed: _skip, child: const Text('Bỏ qua'))]),
        body: Column(children: [
          Padding(padding: const EdgeInsets.fromLTRB(16, 12, 16, 0), child: Row(children: [for (var i = 0; i < 5; i++) Expanded(child: Container(height: 4, margin: const EdgeInsets.only(right: 4), decoration: BoxDecoration(color: i <= step ? c.accent : c.surface2, borderRadius: BorderRadius.circular(2))))])),
          Expanded(child: ListView(padding: const EdgeInsets.all(16), children: [questions[step].animate(key: ValueKey(step)).fadeIn(duration: 250.ms).slideX(begin: 0.05), const SizedBox(height: 16), if (step == 4) summaryCard])),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(children: [
                if (step > 0) OutlinedButton(onPressed: () => setState(() => step--), child: const Text('Quay lại')),
                const Spacer(),
                FilledButton(onPressed: _busy ? null : () => step < 4 ? setState(() => step++) : _save(), child: Text(step < 4 ? 'Tiếp tục' : 'Lưu và bắt đầu')),
              ]),
            ),
          ),
        ]),
      );
    }
    return Scaffold(
      body: PageBody(
        maxWidth: 1100,
        child: ListView(children: [
          header,
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(flex: 3, child: Column(children: [for (final (i, q) in questions.indexed) Padding(padding: const EdgeInsets.only(bottom: 16), child: q.stagger(context, i, step: 80))])),
            const SizedBox(width: 20),
            Expanded(flex: 2, child: Column(children: [
              summaryCard,
              const SizedBox(height: 16),
              Row(mainAxisAlignment: MainAxisAlignment.end, children: [FilledButton(onPressed: _busy ? null : _save, child: const Text('Lưu và bắt đầu'))]),
            ])),
          ]),
        ]),
      ),
    );
  }

  Widget _progress(BuildContext context, List<String> steps, int active) {
    final c = context.vn;
    return Wrap(spacing: 8, runSpacing: 6, children: [
      for (final (i, s) in steps.indexed)
        Pill(s, color: i < active ? c.up : (i == active ? c.link : c.faint), bg: i == active ? c.accent.withValues(alpha: 0.18) : c.surface2),
    ]);
  }

  Widget _q(String title, List<(String, String, String)> opts, String value, ValueChanged<String> onChanged) {
    final c = context.vn;
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 10),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final o in opts)
            AnimatedContainer(
              duration: 200.ms,
              child: ChoiceChip(
                selected: value == o.$1,
                onSelected: (_) => onChanged(o.$1),
                selectedColor: c.accent,
                labelStyle: TextStyle(color: value == o.$1 ? Colors.white : c.text, fontWeight: FontWeight.w600),
                label: Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [Text(o.$2), if (o.$3.isNotEmpty) Text(o.$3, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w400, color: value == o.$1 ? Colors.white70 : c.muted))])),
              ),
            ),
        ]),
      ]),
    );
  }

  Widget _symbolsQ() {
    final c = context.vn;
    final results = ref.watch(stockSearchProvider(_search.text));
    return AppCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('4. Chọn vài mã để theo dõi', style: Theme.of(context).textTheme.titleMedium),
        Text('Không giới hạn số mã. Danh sách theo dõi đầu tiên sẽ có sẵn các mã này.', style: TextStyle(color: c.muted, fontSize: 12.5)),
        const SizedBox(height: 10),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final s in {...suggested, ...symbols})
            FilterChip(selected: symbols.contains(s), onSelected: (v) => setState(() => v ? symbols.add(s) : symbols.remove(s)), label: Text(s), selectedColor: c.accent, labelStyle: TextStyle(color: symbols.contains(s) ? Colors.white : c.text, fontWeight: FontWeight.w600)),
        ]),
        const SizedBox(height: 10),
        TextField(controller: _search, decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Tìm mã hoặc tên công ty…'), onChanged: (_) => setState(() {})),
        if (_search.text.isNotEmpty)
          results.when(
            data: (rows) => Wrap(spacing: 6, children: [for (final r in rows) ActionChip(label: Text('${r['symbol']} · ${r['name'] ?? ''}'), onPressed: () => setState(() {
                  symbols.add(r['symbol']);
                  _search.clear();
                }))]),
            loading: () => const Padding(padding: EdgeInsets.all(8), child: LinearProgressIndicator()),
            error: (e, _) => const SizedBox.shrink(),
          ),
      ]),
    );
  }
}
