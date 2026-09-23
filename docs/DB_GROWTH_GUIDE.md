# Battery Guard — Medição de crescimento do banco

Este monitor é deliberadamente separado do SQLite do Battery Guard.

O objetivo é medir quanto o banco realmente cresce antes de definir:

- retenção local;
- rollups;
- compressão;
- frequência de upload;
- uso de OneDrive.

## Uso manual

```bash
python3 db_growth_monitor.py
```

O script seleciona o `battery-history.db` mais recentemente modificado entre:

```text
~/battery-history.db
~/Library/Application Support/Battery Guard/battery-history.db
```

Para evitar ambiguidade, prefira informar o banco explicitamente durante a fase atual:

```bash
python3 db_growth_monitor.py \
  --db "$HOME/battery-history.db"
```

## Ver projeção

Depois de pelo menos duas amostras:

```bash
python3 db_growth_monitor.py \
  --db "$HOME/battery-history.db" \
  --summary
```

A projeção passa a ser útil após aproximadamente:

- 24 h: preliminar;
- 72 h: boa aproximação;
- 7 dias: baseline;
- 14–30 dias: planejamento de retenção.

## Arquivo gerado

```text
~/Library/Application Support/Battery Guard/db-growth.csv
```

Campos registrados:

- timestamp;
- tamanho do DB;
- tamanho do WAL;
- tamanho do SHM;
- tamanho total;
- page_size;
- page_count;
- freelist_count;
- tamanho lógico do SQLite.

O monitor não executa `COUNT(*)` nas grandes tabelas em cada coleta, reduzindo overhead.

## Frequência sugerida

Uma amostra por hora é suficiente para planejamento de capacidade.

Não é necessário medir a cada 15 segundos.

## Próximo passo

Depois de 72 horas, calcular:

```text
MB/dia
MB/semana
GB/mês
GB/ano
```

Só então definir a política para OneDrive.
