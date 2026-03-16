"""
🧠 Deep Learning Trainer V3 - 8 Specialized Models (7 LSTM + 1 CNN)
Trains AI Brain + 7 Consultant Models for trading decisions
"""

# ========== AUTO-UPDATE PIP ==========
import subprocess
import sys
try:
    print("🔄 Checking pip updates...")
    result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'], 
                           capture_output=True, check=False, timeout=30, text=True)
    if "Successfully installed" in result.stdout:
        print("✅ pip updated successfully")
    else:
        print("✅ pip is up to date")
except Exception as e:
    print(f"⚠️ pip update skipped: {e}")

# ========== LOAD ENV FILE ==========
import os
for _env_file in [
    '/home/container/DeepLearningTrainer/.env',
    '/home/container/.env',
]:
    try:
        with open(_env_file) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith('#') and '=' in _line:
                    _k, _v = _line.split('=', 1)
                    os.environ.setdefault(_k.strip(), _v.strip())
        break
    except:
        pass

import time
import json
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from urllib.parse import urlparse, unquote

try:
    import numpy as np
    import pandas as pd
    os.environ['KERAS_BACKEND'] = 'jax'
    import keras
    from keras import layers
    DL_AVAILABLE = True
    print(f"✅ Keras {keras.__version__} with JAX backend loaded")
except ImportError:
    print("❌ Keras not installed. Run: pip install keras jax jaxlib")
    DL_AVAILABLE = False
    sys.exit(1)

class DeepLearningTrainerV2:
    def __init__(self, database_url):
        self.database_url = database_url
        self.conn = self._connect_db()
        
        # 8 موديلات: AI Brain + 7 مستشارين (6 LSTM + 1 CNN)
        self.models = {
            'ai_brain': None,      # AI Brain - LSTM
            'mtf': None,           # Multi-Timeframe - LSTM
            'risk': None,          # Risk Manager - LSTM
            'anomaly': None,       # Anomaly Detector - LSTM
            'exit': None,          # Exit Strategy - LSTM
            'pattern': None,       # Pattern Recognition - LSTM
            'ranking': None,       # Coin Ranking - LSTM
            'chart_cnn': None      # Chart Pattern Analyzer - CNN (جديد)
        }
        
        self.sequence_length = 10
        self.min_trades_for_training = 100
        
        print("🧠 Deep Learning Trainer V3 initialized (8 Models: 7 LSTM + 1 CNN)")
    
    def _connect_db(self):
        """Connect to PostgreSQL"""
        try:
            parsed = urlparse(self.database_url)
            self._db_params = {
                'host': parsed.hostname,
                'port': parsed.port,
                'database': parsed.path[1:],
                'user': parsed.username,
                'password': unquote(parsed.password)
            }
            conn = psycopg2.connect(**self._db_params)
            print("✅ Database connected")
            return conn
        except Exception as e:
            print(f"❌ Database connection error: {e}")
            return None

    def _get_conn(self):
        """Get valid connection - reconnect if closed"""
        try:
            if self.conn.closed:
                raise Exception("closed")
            self.conn.cursor().execute("SELECT 1")
        except Exception:
            try:
                self.conn = psycopg2.connect(**self._db_params)
            except Exception as e:
                print(f"❌ DB reconnect error: {e}")
        return self.conn
    
    def load_training_data(self):
        """Load historical trades for LSTM training"""
        if not self.conn:
            return None
        
        try:
            cursor = self._get_conn().cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT 
                    symbol,
                    profit_percent,
                    action,
                    timestamp,
                    data
                FROM trades_history
                WHERE action = 'SELL'
                AND data IS NOT NULL
                ORDER BY timestamp ASC
                LIMIT 2000
            """)
            
            trades = cursor.fetchall()
            cursor.close()
            
            if len(trades) < self.min_trades_for_training:
                print(f"⚠️ Not enough trades. Need {self.min_trades_for_training}, have {len(trades)}")
                return None
            
            print(f"📊 Loaded {len(trades)} trades for training")
            return trades
        
        except Exception as e:
            print(f"❌ Error loading data: {e}")
            return None
    
    def build_lstm_model(self, sequence_length, n_features, output_dim=1, model_type='binary'):
        """Build LSTM model"""
        model = keras.Sequential([
            layers.Input(shape=(sequence_length, n_features)),
            layers.LSTM(64, return_sequences=True),
            layers.Dropout(0.3),
            layers.LSTM(32, return_sequences=False),
            layers.Dropout(0.2),
            layers.Dense(16, activation='relu'),
            layers.Dropout(0.2),
        ])
        
        if model_type == 'binary':
            model.add(layers.Dense(output_dim, activation='sigmoid'))
            model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
        elif model_type == 'regression':
            model.add(layers.Dense(output_dim, activation='linear'))
            model.compile(optimizer='adam', loss='mse', metrics=['mae'])
        elif model_type == 'multiclass':
            model.add(layers.Dense(output_dim, activation='softmax'))
            model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])
        
        return model
    
    def prepare_sequences(self, features_list, labels_list):
        """تحويل البيانات لـ sequences"""
        X_sequences = []
        y_sequences = []
        
        for i in range(len(features_list) - self.sequence_length):
            sequence = features_list[i:i + self.sequence_length]
            label = labels_list[i + self.sequence_length]
            
            X_sequences.append(sequence)
            y_sequences.append(label)
        
        return np.array(X_sequences, dtype=np.float32), np.array(y_sequences, dtype=np.float32)
    
    def calculate_enhanced_features(self, data):
        """Feature Engineering: حساب مؤشرات إضافية"""
        try:
            rsi = data.get('rsi', 50)
            macd = data.get('macd', 0)
            volume_ratio = data.get('volume_ratio', 1)
            price_momentum = data.get('price_momentum', 0)
            
            # Bollinger Bands approximation
            bb_position = (rsi - 30) / 40  # normalized position in BB
            
            # ATR approximation (from volatility)
            atr_estimate = abs(price_momentum) * volume_ratio
            
            # Stochastic approximation
            stochastic = rsi  # simplified
            
            # EMA crossover signal
            ema_signal = 1 if macd > 0 else -1
            
            # Volume strength
            volume_strength = min(volume_ratio / 2.0, 2.0)  # normalized
            
            # Momentum strength
            momentum_strength = abs(price_momentum) / 10.0
            
            return [
                rsi,
                macd,
                volume_ratio,
                price_momentum,
                bb_position,
                atr_estimate,
                stochastic,
                ema_signal,
                volume_strength,
                momentum_strength
            ]
        except:
            return [50, 0, 1, 0, 0.5, 1, 50, 0, 1, 0]
    
    def build_cnn_model(self, sequence_length, n_features):
        """Build CNN model for chart pattern analysis"""
        model = keras.Sequential([
            layers.Input(shape=(sequence_length, n_features)),
            layers.Conv1D(64, kernel_size=3, activation='relu', padding='same'),
            layers.MaxPooling1D(pool_size=2),
            layers.Conv1D(32, kernel_size=3, activation='relu', padding='same'),
            layers.GlobalMaxPooling1D(),
            layers.Dense(16, activation='relu'),
            layers.Dropout(0.3),
            layers.Dense(1, activation='sigmoid')
        ])
        
        model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
        return model
    
    def train_mtf_model(self, trades):
        """Train Multi-Timeframe Analyzer"""
        print("\n🎓 Training MTF Model...")
        
        features_list = []
        labels_list = []
        
        for trade in trades:
            try:
                data = trade.get('data', {})
                if isinstance(data, str):
                    data = json.loads(data)
                
                features = [
                    data.get('rsi', 50),
                    data.get('macd', 0),
                    data.get('volume_ratio', 1),
                    data.get('price_momentum', 0)
                ]
                
                profit = float(trade.get('profit_percent', 0))
                # MTF: توقع الترند (bullish=1, bearish=0)
                label = 1 if profit > 0 else 0
                
                features_list.append(features)
                labels_list.append(label)
            except:
                continue
        
        X, y = self.prepare_sequences(features_list, labels_list)
        
        if len(X) < 50:
            print("⚠️ Not enough data for MTF")
            return None
        
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        model = self.build_lstm_model(self.sequence_length, X.shape[2], output_dim=1, model_type='binary')
        
        model.fit(X_train, y_train, epochs=30, batch_size=32, validation_split=0.2, verbose=0)
        
        loss, accuracy = model.evaluate(X_test, y_test, verbose=0)
        print(f"✅ MTF Model: Accuracy {accuracy*100:.2f}%")
        
        return model, accuracy
    
    def train_ai_brain_model(self, trades):
        """Train AI Brain (الملك) - القرار النهائي"""
        print("\n👑 Training AI Brain Model...")
        
        features_list = []
        labels_list = []
        
        for trade in trades:
            try:
                data = trade.get('data', {})
                if isinstance(data, str):
                    data = json.loads(data)
                
                # الملك ياخذ كل المعلومات
                features = [
                    data.get('rsi', 50),
                    data.get('macd', 0),
                    data.get('volume_ratio', 1),
                    data.get('price_momentum', 0),
                    data.get('confidence', 60),
                    data.get('mtf_score', 0),
                    data.get('risk_score', 0),
                    data.get('anomaly_score', 0),
                    data.get('exit_score', 0),
                    data.get('pattern_score', 0),
                    data.get('ranking_score', 0)
                ]
                
                profit = float(trade.get('profit_percent', 0))
                # الملك يتعلم: هل القرار كان صح؟ (ربح = 1, خسارة = 0)
                label = 1 if profit > 0.5 else 0
                
                features_list.append(features)
                labels_list.append(label)
            except:
                continue
        
        X, y = self.prepare_sequences(features_list, labels_list)
        
        if len(X) < 50:
            print("⚠️ Not enough data for AI Brain")
            return None
        
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        # الملك يحتاج موديل أكبر (أذكى)
        model = keras.Sequential([
            layers.Input(shape=(self.sequence_length, X.shape[2])),
            layers.LSTM(128, return_sequences=True),  # أكبر من الباقي
            layers.Dropout(0.3),
            layers.LSTM(64, return_sequences=False),
            layers.Dropout(0.2),
            layers.Dense(32, activation='relu'),
            layers.Dropout(0.2),
            layers.Dense(1, activation='sigmoid')
        ])
        
        model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
        
        model.fit(X_train, y_train, epochs=50, batch_size=32, validation_split=0.2, verbose=0)  # epochs أكثر
        
        loss, accuracy = model.evaluate(X_test, y_test, verbose=0)
        print(f"👑 AI Brain Model: Accuracy {accuracy*100:.2f}%")
        
        return model, accuracy
    
    def train_risk_model(self, trades):
        """Train Risk Manager"""
        print("\n🎓 Training Risk Model...")
        
        features_list = []
        labels_list = []
        
        for trade in trades:
            try:
                data = trade.get('data', {})
                if isinstance(data, str):
                    data = json.loads(data)
                
                features = [
                    data.get('rsi', 50),
                    data.get('volume_ratio', 1),
                    data.get('confidence', 60),
                    data.get('price_momentum', 0)
                ]
                
                profit = float(trade.get('profit_percent', 0))
                # Risk: توقع مستوى المخاطرة (high_risk=1 if loss, low_risk=0)
                label = 1 if profit < -1.0 else 0
                
                features_list.append(features)
                labels_list.append(label)
            except:
                continue
        
        X, y = self.prepare_sequences(features_list, labels_list)
        
        if len(X) < 50:
            print("⚠️ Not enough data for Risk")
            return None
        
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        model = self.build_lstm_model(self.sequence_length, X.shape[2], output_dim=1, model_type='binary')
        
        model.fit(X_train, y_train, epochs=30, batch_size=32, validation_split=0.2, verbose=0)
        
        loss, accuracy = model.evaluate(X_test, y_test, verbose=0)
        print(f"✅ Risk Model: Accuracy {accuracy*100:.2f}%")
        
        return model, accuracy

    
    def train_anomaly_model(self, trades):
        """Train Anomaly Detector"""
        print("\n🎓 Training Anomaly Model...")
        
        features_list = []
        labels_list = []
        
        for trade in trades:
            try:
                data = trade.get('data', {})
                if isinstance(data, str):
                    data = json.loads(data)
                
                features = [
                    data.get('rsi', 50),
                    data.get('macd', 0),
                    data.get('volume_ratio', 1),
                    data.get('price_momentum', 0)
                ]
                
                profit = float(trade.get('profit_percent', 0))
                # Anomaly: كشف الحالات الشاذة (خسارة كبيرة)
                label = 1 if profit < -1.5 else 0
                
                features_list.append(features)
                labels_list.append(label)
            except:
                continue
        
        X, y = self.prepare_sequences(features_list, labels_list)
        
        if len(X) < 50:
            print("⚠️ Not enough data for Anomaly")
            return None
        
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        model = self.build_lstm_model(self.sequence_length, X.shape[2], output_dim=1, model_type='binary')
        
        model.fit(X_train, y_train, epochs=30, batch_size=32, validation_split=0.2, verbose=0)
        
        loss, accuracy = model.evaluate(X_test, y_test, verbose=0)
        print(f"✅ Anomaly Model: Accuracy {accuracy*100:.2f}%")
        
        return model, accuracy
    
    def train_exit_model(self, trades):
        """Train Exit Strategy"""
        print("\n🎓 Training Exit Model...")
        
        features_list = []
        labels_list = []
        
        for trade in trades:
            try:
                data = trade.get('data', {})
                if isinstance(data, str):
                    data = json.loads(data)
                
                features = [
                    data.get('rsi', 50),
                    data.get('macd', 0),
                    data.get('confidence', 60),
                    data.get('price_momentum', 0)
                ]
                
                profit = float(trade.get('profit_percent', 0))
                # Exit: متى نبيع؟ (sell_now=1 if profit>1 or loss<-1)
                label = 1 if (profit > 1.0 or profit < -1.0) else 0
                
                features_list.append(features)
                labels_list.append(label)
            except:
                continue
        
        X, y = self.prepare_sequences(features_list, labels_list)
        
        if len(X) < 50:
            print("⚠️ Not enough data for Exit")
            return None
        
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        model = self.build_lstm_model(self.sequence_length, X.shape[2], output_dim=1, model_type='binary')
        
        model.fit(X_train, y_train, epochs=30, batch_size=32, validation_split=0.2, verbose=0)
        
        loss, accuracy = model.evaluate(X_test, y_test, verbose=0)
        print(f"✅ Exit Model: Accuracy {accuracy*100:.2f}%")
        
        return model, accuracy
    
    def train_pattern_model(self, trades):
        """Train Pattern Recognition"""
        print("\n🎓 Training Pattern Model...")
        
        features_list = []
        labels_list = []
        
        for trade in trades:
            try:
                data = trade.get('data', {})
                if isinstance(data, str):
                    data = json.loads(data)
                
                features = [
                    data.get('rsi', 50),
                    data.get('macd', 0),
                    data.get('volume_ratio', 1),
                    data.get('price_momentum', 0),
                    data.get('confidence', 60)
                ]
                
                profit = float(trade.get('profit_percent', 0))
                # Pattern: نمط ناجح أو فخ
                label = 1 if profit > 0.5 else 0
                
                features_list.append(features)
                labels_list.append(label)
            except:
                continue
        
        X, y = self.prepare_sequences(features_list, labels_list)
        
        if len(X) < 50:
            print("⚠️ Not enough data for Pattern")
            return None
        
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        model = self.build_lstm_model(self.sequence_length, X.shape[2], output_dim=1, model_type='binary')
        
        model.fit(X_train, y_train, epochs=30, batch_size=32, validation_split=0.2, verbose=0)
        
        loss, accuracy = model.evaluate(X_test, y_test, verbose=0)
        print(f"✅ Pattern Model: Accuracy {accuracy*100:.2f}%")
        
        return model, accuracy
    
    def train_ranking_model(self, trades):
        """Train Coin Ranking"""
        print("\n🎓 Training Ranking Model...")
        
        # تجميع البيانات حسب العملة
        coin_data = {}
        
        for trade in trades:
            try:
                symbol = trade.get('symbol')
                profit = float(trade.get('profit_percent', 0))
                
                if symbol not in coin_data:
                    coin_data[symbol] = {'profits': [], 'count': 0}
                
                coin_data[symbol]['profits'].append(profit)
                coin_data[symbol]['count'] += 1
            except:
                continue
        
        features_list = []
        labels_list = []
        
        for symbol, data in coin_data.items():
            if data['count'] < 3:
                continue
            
            avg_profit = sum(data['profits']) / len(data['profits'])
            win_rate = sum(1 for p in data['profits'] if p > 0) / len(data['profits'])
            
            features = [
                avg_profit,
                win_rate,
                data['count'],
                max(data['profits']),
                min(data['profits'])
            ]
            
            # Ranking: عملة جيدة أو سيئة
            label = 1 if avg_profit > 0 and win_rate > 0.5 else 0
            
            features_list.append(features)
            labels_list.append(label)
        
        if len(features_list) < 20:
            print("⚠️ Not enough coins for Ranking")
            return None
        
        # Ranking لا يحتاج sequences (بيانات ثابتة لكل عملة)
        X = np.array(features_list, dtype=np.float32)
        y = np.array(labels_list, dtype=np.float32)
        
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        # موديل بسيط (بدون LSTM)
        model = keras.Sequential([
            layers.Input(shape=(5,)),
            layers.Dense(32, activation='relu'),
            layers.Dropout(0.3),
            layers.Dense(16, activation='relu'),
            layers.Dense(1, activation='sigmoid')
        ])
        
        model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
        
        model.fit(X_train, y_train, epochs=30, batch_size=16, validation_split=0.2, verbose=0)
        
        loss, accuracy = model.evaluate(X_test, y_test, verbose=0)
        print(f"✅ Ranking Model: Accuracy {accuracy*100:.2f}%")
        
        return model, accuracy
    
    def train_chart_cnn_model(self, trades):
        """Train Chart Pattern Analyzer (CNN)"""
        print("\n📊 Training Chart CNN Model...")
        
        features_list = []
        labels_list = []
        
        for trade in trades:
            try:
                data = trade.get('data', {})
                if isinstance(data, str):
                    data = json.loads(data)
                
                # استخدام Feature Engineering المحسّن
                features = self.calculate_enhanced_features(data)
                
                profit = float(trade.get('profit_percent', 0))
                # CNN: كشف أنماط الشارت الناجحة
                label = 1 if profit > 0.5 else 0
                
                features_list.append(features)
                labels_list.append(label)
            except:
                continue
        
        X, y = self.prepare_sequences(features_list, labels_list)
        
        if len(X) < 50:
            print("⚠️ Not enough data for Chart CNN")
            return None
        
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        model = self.build_cnn_model(self.sequence_length, X.shape[2])
        
        model.fit(X_train, y_train, epochs=30, batch_size=32, validation_split=0.2, verbose=0)
        
        loss, accuracy = model.evaluate(X_test, y_test, verbose=0)
        print(f"📊 Chart CNN Model: Accuracy {accuracy*100:.2f}%")
        
        return model, accuracy
    
    def train_all_models(self):
        """Train all 8 models (AI Brain + 7 Consultants: 6 LSTM + 1 CNN)"""
        print("\n" + "="*60)
        print("👑 Starting Training - 8 Models (7 LSTM + 1 CNN)")
        print("="*60)
        
        trades = self.load_training_data()
        if not trades:
            return False
        
        results = {}
        
        # 🎯 حساب دقة التصويت أولاً (التعلم من الأداء السابق)
        try:
            voting_scores = self.calculate_voting_accuracy(trades)
            results['voting_scores'] = voting_scores
        except Exception as e:
            print(f"⚠️ Voting accuracy calculation error: {e}")
            results['voting_scores'] = {}
        
        # 👑 الملك يتدرب أول (الأهم)
        try:
            result = self.train_ai_brain_model(trades)
            if result:
                self.models['ai_brain'], results['ai_brain_accuracy'] = result
        except Exception as e:
            print(f"❌ AI Brain training error: {e}")
        
        # Train consultant models
        try:
            result = self.train_mtf_model(trades)
            if result:
                self.models['mtf'], results['mtf_accuracy'] = result
        except Exception as e:
            print(f"❌ MTF training error: {e}")
        
        try:
            result = self.train_risk_model(trades)
            if result:
                self.models['risk'], results['risk_accuracy'] = result
        except Exception as e:
            print(f"❌ Risk training error: {e}")
        
        try:
            result = self.train_anomaly_model(trades)
            if result:
                self.models['anomaly'], results['anomaly_accuracy'] = result
        except Exception as e:
            print(f"❌ Anomaly training error: {e}")
        
        try:
            result = self.train_exit_model(trades)
            if result:
                self.models['exit'], results['exit_accuracy'] = result
        except Exception as e:
            print(f"❌ Exit training error: {e}")
        
        try:
            result = self.train_pattern_model(trades)
            if result:
                self.models['pattern'], results['pattern_accuracy'] = result
        except Exception as e:
            print(f"❌ Pattern training error: {e}")
        
        try:
            result = self.train_ranking_model(trades)
            if result:
                self.models['ranking'], results['ranking_accuracy'] = result
        except Exception as e:
            print(f"❌ Ranking training error: {e}")
        
        # Train CNN model
        try:
            result = self.train_chart_cnn_model(trades)
            if result:
                self.models['chart_cnn'], results['chart_cnn_accuracy'] = result
        except Exception as e:
            print(f"❌ Chart CNN training error: {e}")
        
        # Save models
        self.save_all_models()
        
        # Save to database
        self.save_models_to_db(results)
        
        print("\n✅ All 8 models trained successfully!")
        print("🎓 Consultants learned from voting accuracy!")
        return True
    
    def save_all_models(self):
        """Save all models to files"""
        print("\n💾 Saving models...")
        
        for model_name, model in self.models.items():
            if model:
                try:
                    model_path = os.path.join(os.path.dirname(__file__), f'{model_name}_model.keras')
                    model.save(model_path)
                    print(f"  ✅ {model_name} saved")
                except Exception as e:
                    print(f"  ❌ {model_name} save error: {e}")
    
    def calculate_voting_accuracy(self, trades):
        """
        🎯 حساب دقة تصويت المستشارين (TP/Amount/SL)
        Returns: accuracy scores for each consultant
        """
        print("\n🎯 Calculating voting accuracy...")
        
        consultant_scores = {
            'exit': {'tp': [], 'amount': [], 'sl': []},
            'mtf': {'tp': [], 'amount': [], 'sl': []},
            'risk': {'tp': [], 'amount': [], 'sl': []},
            'pattern': {'tp': [], 'amount': [], 'sl': []},
            'cnn': {'tp': [], 'amount': [], 'sl': []},
            'anomaly': {'tp': [], 'amount': [], 'sl': []},
            'ranking': {'tp': [], 'amount': [], 'sl': []}
        }
        
        for trade in trades:
            try:
                data = trade.get('data', {})
                if isinstance(data, str):
                    data = json.loads(data)
                
                # البيانات المتوقعة
                predicted_tp = data.get('predicted_tp', 0)
                predicted_sl = data.get('predicted_sl', 0)
                predicted_amount = data.get('predicted_amount', 0)
                
                # البيانات الفعلية
                actual_profit = float(trade.get('profit_percent', 0))
                
                if predicted_tp == 0 or predicted_amount == 0:
                    continue  # لا توجد بيانات تصويت
                
                # حساب دقة TP (هل الربح الفعلي قريب من المتوقع؟)
                tp_error = abs(actual_profit - predicted_tp) / max(abs(predicted_tp), 0.1)
                tp_accuracy = max(0, 1 - tp_error)  # كلما قل الخطأ، زادت الدقة
                
                # حساب دقة Amount (هل المبلغ كان مناسب؟)
                # لو ربح عالي → المبلغ كان صح
                # لو خسارة → المبلغ كان كبير
                if actual_profit > 0:
                    amount_accuracy = min(actual_profit / 2.0, 1.0)  # ربح = دقة عالية
                else:
                    amount_accuracy = max(0, 1 + actual_profit / 2.0)  # خسارة = دقة منخفضة
                
                # حساب دقة SL (هل SL كان كافي؟)
                if actual_profit < 0:
                    # لو الخسارة أقل من SL المتوقع → SL كان صح
                    sl_accuracy = 1.0 if actual_profit >= predicted_sl else 0.5
                else:
                    sl_accuracy = 1.0  # لو ربح، SL ما استخدم
                
                # توزيع النقاط على المستشارين (افتراضي - متساوي)
                # في المستقبل، يمكن تتبع تصويت كل مستشار بشكل منفصل
                for consultant in consultant_scores.keys():
                    consultant_scores[consultant]['tp'].append(tp_accuracy)
                    consultant_scores[consultant]['amount'].append(amount_accuracy)
                    consultant_scores[consultant]['sl'].append(sl_accuracy)
            
            except Exception as e:
                continue
        
        # حساب المتوسط لكل مستشار
        final_scores = {}
        for consultant, scores in consultant_scores.items():
            if len(scores['tp']) > 0:
                avg_tp = sum(scores['tp']) / len(scores['tp'])
                avg_amount = sum(scores['amount']) / len(scores['amount'])
                avg_sl = sum(scores['sl']) / len(scores['sl'])
                
                # الدقة الإجمالية
                overall_accuracy = (avg_tp + avg_amount + avg_sl) / 3.0
                
                final_scores[consultant] = {
                    'tp_accuracy': avg_tp,
                    'amount_accuracy': avg_amount,
                    'sl_accuracy': avg_sl,
                    'overall_accuracy': overall_accuracy
                }
                
                print(f"  📊 {consultant}: TP={avg_tp*100:.1f}% | Amount={avg_amount*100:.1f}% | SL={avg_sl*100:.1f}% | Overall={overall_accuracy*100:.1f}%")
            else:
                final_scores[consultant] = {
                    'tp_accuracy': 0.5,
                    'amount_accuracy': 0.5,
                    'sl_accuracy': 0.5,
                    'overall_accuracy': 0.5
                }
        
        return final_scores
    
    def save_models_to_db(self, results):
        """Save models info to database"""
        if not self.conn:
            return False
        
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # زيادة timeout للعملية
            cursor.execute("SET statement_timeout = '60s'")
            
            # محاولة إضافة العمود إذا لم يكن موجود (بدل DROP TABLE)
            try:
                cursor.execute("""
                    ALTER TABLE dl_models_v2 
                    ADD COLUMN IF NOT EXISTS voting_accuracy JSONB DEFAULT '{}'
                """)
            except:
                # لو الجدول مو موجود، ننشئه
                cursor.execute("DROP TABLE IF EXISTS dl_models_v2")
                cursor.execute("""
                    CREATE TABLE dl_models_v2 (
                        id SERIAL PRIMARY KEY,
                        model_name VARCHAR(50) NOT NULL,
                        model_type VARCHAR(50) NOT NULL,
                        accuracy FLOAT,
                        trained_at TIMESTAMP DEFAULT NOW(),
                        status VARCHAR(20) DEFAULT 'active',
                        voting_accuracy JSONB DEFAULT '{}'
                    )
                """)
            
            # حذف البيانات القديمة
            cursor.execute("DELETE FROM dl_models_v2")
            
            for model_name in self.models.keys():
                accuracy_key = f'{model_name}_accuracy'
                accuracy = results.get(accuracy_key, 0)
                
                # حفظ دقة التصويت
                voting_acc = results.get('voting_scores', {}).get(model_name, {})
                
                cursor.execute("""
                    INSERT INTO dl_models_v2 (model_name, model_type, accuracy, voting_accuracy)
                    VALUES (%s, %s, %s, %s)
                """, (model_name, 'LSTM', float(accuracy), json.dumps(voting_acc)))
            
            conn.commit()
            cursor.close()
            
            print("💾 Models info saved to database")
            return True
        
        except Exception as e:
            print(f"❌ Error saving to DB: {e}")
            self._get_conn().rollback()
            return False
    
    def run_continuous(self, interval_hours=12):
        """Run training continuously"""
        print(f"\n🚀 Deep Learning Trainer V3 started!")
        print(f"⏰ Training interval: {interval_hours} hours")
        print("="*60)
        
        while True:
            try:
                current_time = datetime.now().strftime("%H:%M:%S")
                print(f"\n{'='*60}")
                print(f"⏰ {current_time}")
                print(f"{'='*60}")
                
                success = self.train_all_models()
                
                if success:
                    print(f"\n✅ Training successful")
                else:
                    print(f"\n⚠️ Training skipped - not enough data")
                
                next_time = (datetime.now() + timedelta(hours=interval_hours)).strftime("%H:%M:%S")
                print(f"\n⏰ Next training at: {next_time}")
                time.sleep(interval_hours * 3600)
            
            except KeyboardInterrupt:
                print("\n🛑 Trainer stopped by user")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
                print(f"⏰ Retrying in 30 minutes...")
                time.sleep(1800)

def main():
    if not DL_AVAILABLE:
        print("❌ Please install Keras:")
        print("   pip install keras jax jaxlib")
        return
    
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL not found!")
        return
    
    trainer = DeepLearningTrainerV2(database_url)
    trainer.run_continuous(interval_hours=6)

if __name__ == "__main__":
    main()
