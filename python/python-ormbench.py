#!/usr/bin/python
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Name: python-ormbench.py
#
# Description:
#   A simple (and still stupid) port of python-mysqlbench to sqlalchemy.
#
# TODO:
#   - Supress using raw SQL statements.
#   - Lots of refactorings.
#
#   http://www.mysql.gr.jp/frame/modules/bwiki/index.php?plugin=attach&refer=Contrib&openfile=mysqlbench-0.1.tgz
#
# Author: Masanori Itoh <masanori.itoh@gmail.com>
#
# Original credits are here:
"""
/*
mysqlbench
* 2005-12-16
  - padding filler
  - change output format
* 2004-12-26
  - init
*/
/*
 * $PostgreSQL: pgsql/contrib/pgbench/pgbench.c,v 1.35 2004/11/09 06:09:31 neilc Exp $
 *
 * pgbench: a simple TPC-B like benchmark program for PostgreSQL
 * written by Tatsuo Ishii
 *
 * Copyright (c) 2000  Tatsuo Ishii
 *
 * Permission to use, copy, modify, and distribute this software and
 * its documentation for any purpose and without fee is hereby
 * granted, provided that the above copyright notice appear in all
 * copies and that both that copyright notice and this permission
 * notice appear in supporting documentation, and that the name of the
 * author not be used in advertising or publicity pertaining to
 * distribution of the software without specific, written prior
 * permission. The author makes no representations about the
 * suitability of this software for any purpose.  It is provided "as
 * is" without express or implied warranty.
 */
"""
import sys
import getopt
import _mysql as mysql
import threading
import time
from datetime import datetime, timedelta
import random
#
from sqlalchemy import *
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String
#
Base = declarative_base()
#


class Accounts(Base):
    __tablename__ = 'accounts'
    aid = Column(Integer, primary_key=True)
    bid = Column(Integer)
    abalance = Column(Integer)
    filler = Column(String(84))


class Branches(Base):
    __tablename__ = 'branches'
    bid = Column(Integer, primary_key=True)
    bbalance = Column(Integer)
    filler = Column(String(88))


class History(Base):
    __tablename__ = 'history'
    tid = Column(Integer)
    bid = Column(Integer)
    aid = Column(Integer)
    delta = Column(Integer)
    mtime = Column(DATETIME, nullable=False, onupdate=func.current_timestamp,
                   primary_key=True)
    filler = Column(String(22))


class Tellers(Base):
    __tablename__ = 'tellers'
    tid = Column(Integer, primary_key=True)
    bid = Column(Integer)
    tbalance = Column(Integer)
    filler = Column(String(84))


class MySQLBench(object):
    nbranches = 1
    ntellers = 10
    naccounts = 100000
    #
    is_init_mode = 0
    mysqlhost = ''
    is_no_vacuum = 0
    is_full_vacuum = 0
    mysqlport = 3306
    debug = 1
    ttype = 0
    nclients = 1
    tps = 1
    nxacts = 1
    login = ''
    password = ''
    engine = 'innodb'
    dbname = 'pgbench'
    #
    options = ''
    #
    threads = []
    con_complete = 0

    def usage(self):
        print 'Usage...'

    def parse_arg(self, argv):
        # print 'MySQLBench::parse_arg called.'
        try:
            opts, args = getopt.getopt(argv[1:],
                                   'ih:nvp:dc:t:s:U:P:CSE:D:', [])
        except getopt.GetoptError:
            print sys.exc_info()
            print 'getopt error...'
            sys.exit(2)

        for opt, arg in opts:
            if opt in ('-i'):
                self.is_init_mode += 1
            elif opt in ('-h'):
                self.mysqlhost = arg
            elif opt in ('-n'):
                self.is_no_vacuum += 1
            elif opt in ('-v'):
                self.is_full_vacuum += 1
            elif opt in ('-p'):
                self.mysqlport = arg
            elif opt in ('-d'):
                self.debug += 1
            elif opt in ('-S'):
                self.ttype = 1
            elif opt in ('-c'):
                self.nclients = int(arg)
#            elif opt in ('-C'):
            elif opt in ('-s'):
                self.tps = int(arg)
            elif opt in ('-t'):
                self.nxacts = int(arg)
                if self.nxacts <= 0:
                    print 'wrong number of transactons: %d' % self.nxacts
                    sys.exit(1)
            elif opt in ('-U'):
                self.login = arg
            elif opt in ('-P'):
                self.password = arg
            elif opt in ('-E'):
                self.engine = arg
            elif opt in ('-D'):
                self.dbname = arg
            else:
                usage()
                sys.exit(1)

        # debug for positional argument
        # print argv, len(argv)
        # print opts, len(opts)
        # sys.exit(1)

    def getSession(self):
        # print 'MySQLBench::getSession called.'
        try:
            #
            # create a session object
            #
            uri = 'mysql://%s:%s@%s/%s%s' \
                % (self.login, self.password,
                   self.mysqlhost, self.dbname, self.options)
            engine = create_engine(uri)
            Session = sessionmaker(bind=engine, autocommit=True)
            session = Session()
            return session

        except:
            print sys.exc_info()[0]
            print sys.exc_info()[1]
            sys.exit(0)

    def initialize(self):
        # print 'MySQLBench::initialize called.'

        DDLs = [
            'DROP TABLE IF EXISTS branches',
            'CREATE TABLE branches (bid int PRIMARY KEY, bbalance int, '
                'filler char(88))',
            'DROP TABLE IF EXISTS tellers',
            'CREATE TABLE tellers (tid int PRIMARY KEY, bid int, '
            'tbalance int, filler char(84))',
            'DROP TABLE IF EXISTS accounts',
            'CREATE TABLE accounts (aid int PRIMARY KEY, bid int, '
                'abalance int, filler char(84))',
            'DROP TABLE IF EXISTS history',
            'CREATE TABLE history (tid int, bid int, aid int, '
                'delta int, mtime timestamp, filler char(22))'
            ]
        session = self.getSession()
        for stmt in DDLs:
            if stmt.startswith('CREATE'):
                sql = '%s ENGINE=%s' % (stmt, self.engine)
            else:
                sql = '%s' % stmt
            session.execute(sql)

        session.begin()
        try:
            for i in range(0, self.nbranches * self.tps):
                sql = 'INSERT INTO branches (bid, bbalance, filler) ' \
                    'VALUES (%d, 0, REPEAT(\'b\',88))' % (i + 1)
                session.execute(sql)

            for i in range(0, self.ntellers * self.tps):
                sql = 'INSERT INTO tellers (tid, bid, tbalance, filler) ' \
                    'VALUES (%d, %d, 0, REPEAT(\'t\',84))' \
                    % (i + 1, i / self.ntellers + 1)
                session.execute(sql)

            print 'Filling tables...'
            for i in range(0, self.naccounts * self.tps):
                j = i + 1
                sql = 'INSERT INTO accounts (aid, bid, abalance, filler) ' \
                    'VALUES (%d, %d, %d, REPEAT(\'c\',84))' \
                    % (j, j / self.naccounts, 0)
                session.execute(sql)

            session.commit()
            session.execute('OPTIMIZE TABLE branches, tellers, accounts, history')
        except:
            print sys.exc_info()[0]
            print sys.exc_info()[1]
            session.rollback()
            raise

        session.close()
        #self.doClose(conn)
        print 'done.'

    def doOne(self, id):
        #print 'doOne called. ident: %d id: %d' %
        #(threading.currentThread().ident, id)
        # establish a connection
        session = self.getSession()

        # test
        #if self.debug:
        #    conn.query('SELECT connection_id()')
        #    print 'id: %d con_id: %s' %
        #    (id, conn.store_result().fetch_row(maxrows=1, how=1))
        # count up the global connection counter and notify.
        self.cv_conn.acquire()
        self.con_complete += 1
        self.cv_conn.notify()
        self.cv_conn.release()

        # wait for other threads get ready
        self.cv.acquire()
        while not self.ready:
            self.cv.wait()
        self.cv.release()

        # generate workload
        cnt = 0
        ecnt = 0
        for n in range(0, self.nxacts):
            #
            # in random.randint(begin, end) case, begin and end are inclusive.
            aid = random.randint(1, self.naccounts * self.tps)
            bid = random.randint(1, self.nbranches * self.tps)
            tid = random.randint(1, self.ntellers * self.tps)
            # print 'tx: %d aid: %d bid: %d tid: %d' % (n, aid, bid, tid)
            delta = random.randint(1, 1000)

            # Q0
            session.begin()
            try:
                # Q1
                sql = 'UPDATE accounts SET abalance = abalance + %d ' \
                    'WHERE aid = %d' % (delta, aid)
                result = session.execute(sql)
                # Q2
                sql = 'SELECT abalance FROM accounts WHERE aid = %d' % (aid)
                result = session.execute(sql)
                result.fetchall()
                # Q3
                sql = ' UPDATE tellers SET tbalance = tbalance + %d ' \
                    'WHERE tid = %d' % (delta, tid)
                result = session.execute(sql)
                # Q4
                sql = 'UPDATE branches SET bbalance = bbalance + %d ' \
                    'WHERE bid = %d' % (delta, bid)
                result = session.execute(sql)
                # Q5
                sql = 'INSERT INTO history (tid,bid,aid,delta,mtime, filler) '\
                    'VALUES (%d,%d,%d,%d, NOW(), \'aaaaaaaaaaaaaaaaaaaaaa\')' \
                    % (tid, bid, aid, delta)
                result = session.execute(sql)
                # Q6
                result = session.commit()
                cnt += 1
            except:
                print sys.exc_info()[0]
                print sys.exc_info()[1]
                session.rollback()
                ecnt += 1
                raise

        session.close()
        self.threads[id]['cnt'] = cnt
        self.threads[id]['ecnt'] = ecnt
        return

    def print_results(self, ts1, ts2, ts3):
        normal_xacts = 0
        for i in range(0, self.nclients):
            normal_xacts += self.threads[i]['cnt']

        t1 = (ts3 - ts1)
        t2 = (ts3 - ts2)
        t1 = float(normal_xacts) / t1.total_seconds()
        t2 = float(normal_xacts) / t2.total_seconds()

        if self.ttype == 0:
            test = 'TPC-B (sort of)'
        else:
            test = 'SELECT only'
        print 'transaction type                    . . . : %s' % test
        print 'scaling factor                      . . . : %d' % self.tps
        print 'number of clients                     . . : %d' \
            % self.nclients
        print 'number of transactions per client         : %d' \
            % self.nxacts
        print 'number of transactions actually processed : %d/%d' \
            % (normal_xacts, self.nxacts * self.nclients)
        print 'tps (include connections establishing)  . : %f' % t1
        print 'tps (exclude connections establishing)  . : %f' % t2

        return

    def run(self):
        # print 'MySQLBench::run called.'

        #self.conn = self.doConnect()
        session = self.getSession()

        # scaling factor should be the same as count(bid) from branches.
        result = session.execute("SELECT count(bid) FROM branches")
        self.tps = int(result.fetchone()[0])
        # rows = self.conn.store_result().fetch_row(maxrows=1, how=1)
        # self.tps = int(rows[0]['count(bid)'])
        # print 'DEBUG: scaling factor = %d' % self.tps

        if self.is_no_vacuum is not 0:
            print 'starting vacuum...'
            session.execute("OPTIMIZE TABLE branches")
            session.execute("OPTIMIZE TABLE tellers")
            session.execute("OPTIMIZE TABLE history")
            session.execute("OPTIMIZE TABLE branches")

        if self.is_full_vacuum is not 0:
            session.execute("OPTIMIZE TABLE accounts")
        # close
        session.close()

        self.cv = threading.Condition()
        self.cv_conn = threading.Condition()
        self.ready = False
        self.con_complete = 0

        tv1 = datetime.now()

        #create threads
        for i in range(0, self.nclients):
            t = threading.Thread(target=self.doOne,
                                     name='threadb-%d' % i, args=(i,))
            self.threads.append({'id': i, 'state': 'INIT',
                                     'thread': t, 'conn': None})
            t.start()

        # wait for connection setup of all child threads.
        self.cv_conn.acquire()
        while self.con_complete < self.nclients:
            self.cv_conn.wait()
        self.cv_conn.release()

        tv2 = datetime.now()

        # print 'go...'
        # start all threads
        self.cv.acquire()
        self.ready = True
        self.cv.notifyAll()
        self.cv.release()
        #
        # wait for all threads end up.
        for t in self.threads:
            t['thread'].join()
        print 'all threads completed'

        tv3 = datetime.now()

        self.print_results(tv1, tv2, tv3)


if __name__ == '__main__':
    mb = MySQLBench()
    mb.parse_arg(sys.argv)
    if mb.is_init_mode:
        mb.initialize()
    else:
        mb.run()
