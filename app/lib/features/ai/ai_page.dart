import 'package:flutter/material.dart';

import 'ai_panel.dart';

/// Full-screen AI assistant (phones / deep link).
class AiPage extends StatelessWidget {
  final String? conversationId, symbol, screen;
  const AiPage({super.key, this.conversationId, this.symbol, this.screen});
  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Hỏi AI')),
        body: AiPanel(conversationId: conversationId, context_: {'symbol': symbol, 'screen': screen}),
      );
}
