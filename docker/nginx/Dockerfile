FROM nginx:alpine

# Копируем конфигурацию Nginx
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Создаем директорию для логов
RUN mkdir -p /var/log/nginx

# Открываем порты
EXPOSE 8080
EXPOSE 443

# Запускаем Nginx
CMD ["nginx", "-g", "daemon off;"] 