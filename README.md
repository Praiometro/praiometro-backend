# praiometro-backend
Backend para o app Praiômetro

## Back-end

1. Na máquina que deseja usar como servidor, rode o script `start_mongo.sh` (Linux) ou `start_mongo.bat` (Windows);
2. Inicie o virtual environment com `pyton -m venv venv`;
3. Ative o ambiente virtual. Use `source venv/bin/activate` (Linux) ou `venv\Scripts\activate` (Windows);
4. Instale as dependências com `pip install -r requirements.txt`;
5. Para popular o banco de avaliações, execute `pyton popular_banco.py`. Não é necessário fazer isso novamente;
6. Rode `api_praiometro.py`;
7. Rode `avaliador.py` para calcular as notas médias baseando-se nos dados do banco;
8. Rode `praiometro_hourly.py` para iniciar o script de atualização automática dos dados.
