# Battery Guard — Monitoramento remoto

O monitoramento remoto é opcional e não altera o funcionamento local do Battery Guard.

## Arquitetura

```text
Battery Guard no macOS
        |
        | HTTPS de saída
        v
Relay cloud
        |
        v
Dashboard remoto
```

O Mac envia apenas o snapshot necessário ao monitoramento remoto. O banco SQLite completo, arquivos locais e credenciais de implantação não são enviados pelo mecanismo padrão.

## Configuração local

A configuração real do relay deve permanecer fora do repositório. Exemplo conceitual:

```json
{
  "version": 1,
  "url": "https://<your-worker>.<your-subdomain>.workers.dev",
  "device_token": "<local-secret>",
  "interval_s": 3.0
}
```

Nunca versione:

- tokens de API ou deploy;
- `device_token` ou `viewer_token`;
- URLs reais de pareamento;
- Account IDs ou outros identificadores de conta;
- arquivos locais de configuração do relay.

## Autenticação

A arquitetura separa a credencial utilizada pelo dispositivo para publicar snapshots da credencial utilizada pelo navegador para pareamento. Esses valores são dados operacionais locais e não pertencem ao código-fonte.

## Privacidade

O relay deve receber somente os campos necessários para exibir o estado remoto. A implementação não depende do envio do banco de histórico completo.

## Disponibilidade

O envio depende de o Mac estar ligado, acordado e com acesso à Internet. Quando não há novos snapshots, o dashboard deve representar claramente a idade do último dado recebido.

## Notificações

A versão 0.5.0 documenta o monitoramento remoto, mas não inclui push persistente para o celular. Esse recurso deve ser tratado separadamente para evitar confundir notificações do navegador com push em background.
