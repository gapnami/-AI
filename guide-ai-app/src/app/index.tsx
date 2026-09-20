import React from 'react';
import { SafeAreaView, StyleSheet, StatusBar } from 'react-native';
import { WebView } from 'react-native-webview';

export default function Index() {
  // Render에 배포된 파이썬 메인 웹 주소
  const WEB_URL = 'https://ai-navigator-2usw.onrender.com/';

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="dark-content" />
      <WebView 
        source={{ uri: WEB_URL }} 
        style={styles.webview}
        javaScriptEnabled={true}
        domStorageEnabled={true}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { 
    flex: 1, 
    backgroundColor: '#fff' // 휴대폰 상단 노치/상태바 배경색
  },
  webview: { 
    flex: 1 
  }
});