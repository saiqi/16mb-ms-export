FROM saiqi/16mb-platform:latest

RUN pip3 install boto
RUN echo "deb http://ftp.debian.org/debian jessie-backports main" > /etc/apt/sources.list.d/backports.list
RUN apt-get update && apt-get -t jessie-backports install -y inkscape

COPY ./fonts/*.ttf /usr/local/share/fonts/
RUN fc-cache -fv

RUN mkdir /service 

ADD application /service/application
ADD ./cluster.yml /service

WORKDIR /service
