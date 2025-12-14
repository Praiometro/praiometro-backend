#!/bin/bash

# Cria o diretório de dados se não existir
if [ ! -d "./data/db" ]; then
    echo "Creating data/db directory..."
    mkdir -p ./data/db
fi

echo "Starting MongoDB..."
mongod --dbpath ./data/db