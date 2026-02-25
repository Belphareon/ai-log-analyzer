{{/*
=============================================================================
Conjur Helpers pro Log Analyzer (podle showcase vzoru)
=============================================================================
*/}}

{{/* Určení prostředí prod/nprod */}}
{{- define "env" -}}
{{- if eq (.Values.environment) "prod" -}}
{{- printf "prod" -}}
{{ else }}
{{- printf "nprod" -}}
{{- end -}}
{{- end -}}

{{/* Conjur Follower URL podle prostředí */}}
{{- define "conjurUrl" -}}
{{- if eq (include "env" .) "prod" -}}
{{- printf "https://conjur-follower-prod.kb.cz/api" -}}
{{ else }}
{{- printf "https://conjur-follower-nprod.kb.cz/api" -}}
{{- end -}}
{{- end -}}

{{/* Authn path prefix podle prostředí */}}
{{- define "authnPath" -}}
{{- if eq (include "env" .) "prod" -}}
{{- printf "prod" -}}
{{ else }}
{{- printf "nprod" -}}
{{- end -}}
{{- end -}}

{{/*
=============================================================================
InitContainer pro Conjur Secrets Provider
- Mode: init (jednorázové načtení secrets)
- Destination: k8s_secrets (zapisuje do K8s Secret)
=============================================================================
*/}}
{{- define "conjur.initContainer" -}}
- name: {{ .Values.conjur.containerName }}
  image: {{ .Values.conjur.image }}
  imagePullPolicy: {{ .Values.conjur.imagePullPolicy }}
  env:
    # Pod metadata pro Conjur autentikaci
    - name: MY_POD_NAME
      valueFrom:
        fieldRef:
          fieldPath: metadata.name
    - name: MY_POD_NAMESPACE
      valueFrom:
        fieldRef:
          fieldPath: metadata.namespace
    
    # Cluster info z KB ConfigMap
    - name: CLUSTER_ID
      valueFrom:
        configMapKeyRef:
          name: k8s-kb-cluster-info
          key: cluster_name
    - name: SQUAD_ID
      valueFrom:
        configMapKeyRef:
          name: k8s-kb-cluster-info
          key: squad_ad_group
    
    # Conjur connection
    - name: CONJUR_APPLIANCE_URL
      value: {{ template "conjurUrl" . }}
    - name: CONJUR_AUTHN_URL
      value: {{ template "conjurUrl" . }}/authn-k8s/$(CLUSTER_ID)
    - name: CONJUR_ACCOUNT
      value: kb
    - name: CONJUR_VERSION
      value: "5"
    
    # Provider mode
    - name: CONTAINER_MODE
      value: init
    - name: LOG_LEVEL
      value: debug
    
    # Identity - DŮLEŽITÉ: musí odpovídat registraci v Conjur
    - name: CONJUR_AUTHN_LOGIN
      value: host/conjur/authn-k8s/{{ include "authnPath" . }}/$(SQUAD_ID)/{{ .Values.conjur.applicationId }}/{{ .Values.conjur.componentId }}/k8s-provider
    
    # Secrets destination - K8s Secrets mode
    - name: SECRETS_DESTINATION
      value: k8s_secrets
    - name: K8S_SECRETS
      value: {{ .Values.app.secretName }}
{{- end -}}

{{/*
=============================================================================
Volume pro secrets (jen pokud používáme file mode)
Poznámka: Pro k8s_secrets mode není třeba žádný extra volume
=============================================================================
*/}}
{{- define "conjur.volume" -}}
{{- /* Pro k8s_secrets mode není třeba volume - secrets jsou v K8s Secret */ -}}
{{- end -}}

{{/*
=============================================================================
Alternativní: InitContainer pro push-to-file mode
Použij toto místo conjur.initContainer pokud chceš secrets jako soubory
=============================================================================
*/}}
{{- define "conjur.initContainer.fileMode" -}}
- name: {{ .Values.conjur.containerName }}
  image: {{ .Values.conjur.image }}
  imagePullPolicy: {{ .Values.conjur.imagePullPolicy }}
  env:
    - name: MY_POD_NAME
      valueFrom:
        fieldRef:
          fieldPath: metadata.name
    - name: MY_POD_NAMESPACE
      valueFrom:
        fieldRef:
          fieldPath: metadata.namespace
    - name: CLUSTER_ID
      valueFrom:
        configMapKeyRef:
          name: k8s-kb-cluster-info
          key: cluster_name
    - name: SQUAD_ID
      valueFrom:
        configMapKeyRef:
          name: k8s-kb-cluster-info
          key: squad_ad_group
    - name: CONJUR_APPLIANCE_URL
      value: {{ template "conjurUrl" . }}
    - name: CONJUR_AUTHN_URL
      value: {{ template "conjurUrl" . }}/authn-k8s/$(CLUSTER_ID)
    - name: CONJUR_ACCOUNT
      value: kb
    - name: CONJUR_VERSION
      value: "5"
    - name: CONTAINER_MODE
      value: init
    - name: LOG_LEVEL
      value: debug
    - name: CONJUR_AUTHN_LOGIN
      value: host/conjur/authn-k8s/{{ include "authnPath" . }}/$(SQUAD_ID)/{{ .Values.conjur.applicationId }}/{{ .Values.conjur.componentId }}/k8s-provider
    # Push-to-file mode
    - name: SECRETS_DESTINATION
      value: file
    - name: SECRET_FILE_PATH
      value: /conjur/secrets/
    - name: SECRET_FILE_FORMAT
      value: yaml
  volumeMounts:
    - name: conjur-secrets
      mountPath: /conjur/secrets
{{- end -}}

{{/* Volume pro file mode */}}
{{- define "conjur.volume.fileMode" -}}
- name: conjur-secrets
  emptyDir:
    medium: Memory
{{- end -}}
