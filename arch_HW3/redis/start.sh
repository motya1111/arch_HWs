#!/bin/sh
set -eu
if [ "$NODE_KIND" = sentinel ]; then
  if [ ! -f /data/sentinel.conf ]; then
    cat > /data/sentinel.conf <<CONFIG
port 26379
bind 0.0.0.0
protected-mode no
sentinel resolve-hostnames yes
sentinel announce-hostnames yes
sentinel announce-ip $NODE_NAME
sentinel monitor flights redis-master 6379 2
sentinel down-after-milliseconds flights 1500
sentinel failover-timeout flights 5000
sentinel parallel-syncs flights 1
CONFIG
  fi
  exec redis-server /data/sentinel.conf --sentinel
else
  if [ ! -f /data/redis.conf ]; then
    cat > /data/redis.conf <<CONFIG
port 6379
bind 0.0.0.0
protected-mode no
dir /data
appendonly yes
replica-announce-ip $NODE_NAME
replica-announce-port 6379
CONFIG
    if [ "$NODE_KIND" = replica ]; then
      echo 'replicaof redis-master 6379' >> /data/redis.conf
    fi
  fi
  exec redis-server /data/redis.conf
fi
