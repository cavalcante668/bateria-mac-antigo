# Changelog


## 0.4.0 — 2026-09-20

### Destaques

- Central de Notificações integrada ao Battery Guard.
- Nova aba `Notificações` ao lado de `Bateria` e `Sistema`.
- Badge e contador de notificações não lidas.
- Monitoramento contínuo de novos erros nos logs.
- Alertas de pouco espaço e espaço crítico em disco.
- Notificação após conclusão da análise solicitada de aplicativos/processos em relação ao uso elevado da C1.
- Central de Notificações independente mantida como opção no menu nativo.
- Correção do conflito causado pelo servidor legado `~/Scripts/battery-view.py` na porta 8765.
- Remoção dos backups `.app` de `~/Applications` para impedir versões antigas no Launchpad.

## 2026-09-20 — Sistema de notificações

### Adicionado

- Central de Notificações integrada à interface principal.
- Aba `Notificações` ao lado de `Bateria` e `Sistema`.
- Contador de notificações não lidas.
- Badge no Dock.
- Integração com o menu nativo.
- Worker `alerts`.
- Worker `notifications`.
- Persistência do histórico em JSON.
- Escrita atômica do arquivo de notificações.
- Detecção de novos erros nos logs.
- Controle de eventos duplicados por `repeat_count`.
- Monitoramento de espaço em disco.
- API interna de notificações.
- Marcação individual como lida.
- Ação para marcar todas como lidas.
- Limpeza do histórico.

### Alterado

- A análise solicitada pela interface passa `--notify` ao worker `analysis`.
- A notificação `Análise da C1 concluída` só ocorre após uma análise solicitada pelo usuário.
- Execuções técnicas sem `--notify` não geram esse alerta.
- O launcher passa a iniciar o monitor de alertas.

### Corrigido

- Conflito com o servidor legado `~/Scripts/battery-view.py` na porta 8765.
- Cenário em que o aplicativo novo abria uma interface antiga.
- Execução acidental de `Battery Guard.previous.app`.
- Indexação de backups do Battery Guard pelo Launchpad.
