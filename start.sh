#!/bin/bash

# ==========================================
# 1. 設定與變數
# ==========================================
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
else
    # Fallback
    SECRET_KEY=${SECRET_KEY:-"dev-key"}
    CREATE_SUPERUSER=${CREATE_SUPERUSER:-"admin:admin"}
    REPORT_HOST=${REPORT_HOST:-"localhost:8000"}
    PORT=${PORT:-8000}
    DOCKER_PORT=${DOCKER_PORT:-8000}
    IMAGE_NAME=${IMAGE_NAME:-"bugsink-v13"}
    CONTAINER_NAME=${CONTAINER_NAME:-"bugsink-v13"}
fi

# ==========================================
# 2. 準備資料庫掛載點 (解決 Ghost Database)
# ==========================================
DATA_DIR="$(pwd)/bugsink_data"

echo "📂 [1/6] 準備資料庫目錄: $DATA_DIR"
# 建立目錄
mkdir -p "$DATA_DIR"
# 給予寬鬆權限，確保容器內的 bugsink 使用者(uid:1000) 可以寫入
chmod 777 "$DATA_DIR"

# ==========================================
# 3. 啟動容器
# ==========================================
echo "🛑 [2/6] 重啟容器..."
sudo docker rm -f $CONTAINER_NAME 2>/dev/null

echo "🚀 [3/6] 啟動 Bugsink Docker..."
# 注意：
# 2. -v $DATA_DIR:/data : 將本機目錄掛載進去

DEV_FLAG=""
VOLUME_FLAG=""

while [ "$1" != "" ]; do
    case $1 in
        --dirty )
            echo "Dirty mode activated."
            VOLUME_FLAG="-v $DATA_DIR:/data"
            ;;
        --dev ) 
            echo "Dev mode activated."
	    DEV_FLAG="-v $(pwd)/issues:/app/issues"
            ;;
    esac
    shift # Move to the next argument
done

sudo docker run -d \
    --name $CONTAINER_NAME \
    -e SECRET_KEY="$SECRET_KEY" \
    -e CREATE_SUPERUSER="$CREATE_SUPERUSER" \
    -e REPORT_HOST="$REPORT_HOST" \
    -e PORT=$PORT \
    -p $DOCKER_PORT:$PORT \
    $VOLUME_FLAG \
    $DEV_FLAG \
    $IMAGE_NAME
echo "啟動服務..."
