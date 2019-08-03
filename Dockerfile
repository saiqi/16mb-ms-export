FROM python:3.6-stretch

ADD ./requirements.txt .
RUN pip3 install -r requirements.txt
RUN apt-get update && apt-get install -y imagemagick inkscape

COPY ./fonts/*.ttf ./fonts/*.otf /usr/local/share/fonts/
RUN fc-cache -fv

RUN mkdir /service 

ADD application /service/application
ADD ./cluster.yml /service

WORKDIR /service

ENTRYPOINT ["nameko","run","--config","cluster.yml"]
