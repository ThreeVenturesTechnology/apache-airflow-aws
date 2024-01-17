FROM apache/airflow:2.5.3
COPY requirements.txt .
COPY utils.py .
COPY ./dags /opt/airflow/dags
RUN pip install -r requirements.txt
USER root
RUN mkdir -p /sources/logs /sources/dags /sources/plugins
RUN chown -R airflow /sources/{logs,dags,plugins}
USER airflow
COPY ./dags /sources/dags
